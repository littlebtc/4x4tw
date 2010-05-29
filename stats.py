#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import os
import re
import rankingmodel
import common
import time
from datetime import datetime
from ranker import ranker
from xml.sax import saxutils
from google.appengine.api import urlfetch
from google.appengine.ext import webapp
from google.appengine.api import memcache
from google.appengine.ext.webapp import util
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import datastore
from google.appengine.api import datastore_errors
from google.appengine.api import datastore_types
import logging

def GetRanker():
  key = datastore_types.Key.from_path("app", "default")
  try:
    return ranker.Ranker(datastore.Get(key)["ranker"])
  except datastore_errors.EntityNotFoundError:
    r = ranker.Ranker.Create([0, 1000000], 100)
    app = datastore.Entity("app", name="default")
    app["ranker"] = r.rootkey
    datastore.Put(app)
    return r

class ShowRankStats(webapp.RequestHandler):

  def get(self):
    r = GetRanker()
    user_num = r.TotalRankedScores()
    user_stats = []
    # Rank
    for i in range(24, user_num, 25):
      user_stats.append({'rank': i+1, 'score_average': r.FindScore(i)[0][0]})
    path = os.path.join(os.path.dirname(__file__), 'rank_stats.htm')
    result = template.render(path, {'user_num': user_num, 'user_stats': user_stats})
    self.response.out.write(result)

class ShowExcStats(webapp.RequestHandler):

  def get(self):
    # EXC Rank
    webapp.template.register_template_library('templatetags.spacify')    
    rank_start = 1
    exc_rankers = []
    query = rankingmodel.RankerList.gql('ORDER BY songs_exc DESC LIMIT 50')
    exc_rankers = query.fetch(50)
    for i in range(len(exc_rankers)):
      if i > 0 and exc_rankers[i].songs_exc == exc_rankers[i-1].songs_exc:
        exc_rankers[i].rank = exc_rankers[i-1].rank
      else:
        exc_rankers[i].rank = rank_start + i
    # Rank
    exc_stats = [];
    exc_stats_process = [1,2,3,4,5,6,8,10,15,20,25,30,35]
    for i in exc_stats_process:
      query = rankingmodel.RankerList.gql('WHERE songs_exc >= :1', i)
      count = query.count()
      exc_stats.append({'songs_exc': i, 'count': count})
    #for i in range(24, user_num, 25):
    #  user_stats.append({'rank': i+1, 'score_average': r.FindScore(i)[0][0]})
    path = os.path.join(os.path.dirname(__file__), 'exc_stats.htm')
    result = template.render(path, {'exc_rankers': exc_rankers, 'exc_stats': exc_stats})
    self.response.out.write(result)

class ShowSongStats(webapp.RequestHandler):
  def get(self):
    my_dict = common.GetSongDict()
    query = rankingmodel.RankerList.gql('ORDER BY score_average DESC LIMIT 1000')
    rankers = query.fetch(100)
    ranker_count = 0
    # Initialize
    total_score = dict()
    average_top25 = dict()
    average_top100 = dict()
    top_score = dict()
    for song_id in my_dict.keys():
      total_score[song_id] = 0    
      average_top25[song_id] = 0    
      average_top100[song_id] = 0    
      top_score[song_id] = 0    
    # Go
    for ranker in rankers:
      for i in range(len(ranker.song_list)):
        total_score[ranker.song_list[i]] += ranker.song_scores[i]
        if (top_score[ranker.song_list[i]] < ranker.song_scores[i]):
          top_score[ranker.song_list[i]] = ranker.song_scores[i]
      ranker_count = ranker_count + 1
      if ranker_count == 25:
        average_top25 = total_score.copy()
        for (key,value) in average_top25.items():
          average_top25[key] = value / 25
      if ranker_count == 100:
        average_top100 = total_score.copy()
        for (key,value) in average_top100.items():
          average_top100[key] = value / 100
    
    # Wrap up
    songs = []
    for song_id in common.GetSongSeq():
      song = dict()
      song['name'] = my_dict[song_id]
      song['score_average_top25'] = average_top25[song_id]
      song['score_average_top100'] = average_top100[song_id]
      song['top_score'] = top_score[song_id]
      songs.append(song)
    path = os.path.join(os.path.dirname(__file__), 'song_stats.htm')
    result = template.render(path, {'songs': songs})
    self.response.out.write(result)

def main():
  application = webapp.WSGIApplication([
                ('/stats/rank', ShowRankStats),
                ('/stats/exc', ShowExcStats),
                ('/stats/song', ShowSongStats),
                ],debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
