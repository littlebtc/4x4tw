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
from google.appengine.api.labs import taskqueue
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

class UpdateUser(webapp.RequestHandler):
  def post(self):
    friend_id = self.request.get('friend_id','')
    try:
      friend_id = long(friend_id)
    except:
      logging.error('Updater Error: Invalid Friend ID')
      return
    old_tbs = self.request.get('tbs','')
    try:
      old_tbs = long(old_tbs)
    except:
      logging.warning('Updater Error: Invalid TBS')
      old_tbs = 0
    
       
    # Connect to 573, checking player location
    try:
      url = 'https://www.ea-pass.konami.jp/contents/jubeat/ripples/play_top.do?fid=' + str(friend_id)
      result = urlfetch.fetch(url=url)
    except:
      logging.error('573 is down (playerdata, urlfetch exception)')
      return
    if result.status_code != 200:
      logging.error('573 is down (HTTP %d)' % result.status_code)
      return
    page_content = result.content
    if page_content.find('error') > -1 or page_content.find('<div id="playerNameBox">') == -1:
      logging.warning('Page fetch error. Is 573 down?')
      return
    tbs_rank_match = re.search("<h5>([0-9]+)[^0-9<]*([0-9]+)位<\/h5>", page_content, re.UNICODE)
    if tbs_rank_match is None:
      r = GetRanker()
      r.SetScore(str(friend_id), None)
      ranker = rankingmodel.RankerList.gql('WHERE friend_id = :1', friend_id).get()
      if ranker is None:
        logging.error('Updater Error: Friend ID is not existed')
        return
      ranker.delete()
      logging.warning(str(friend_id) + 'is set to inpublic. Deleted.')
      return
    tbs = int(tbs_rank_match.group(1))
    tbs_rank = int(tbs_rank_match.group(2))
    if old_tbs > 0:
      if old_tbs == tbs:
        ranker = rankingmodel.RankerList.gql('WHERE friend_id = :1', friend_id).get()
        if ranker is None:
          logging.error('Updater Error: Friend ID is not existed')
          return
        ranker.last_updated = datetime.utcnow()
        ranker.put()
        logging.info(str(friend_id) + ': TBS is the same as in the DB. Won\'t update.')
        return
    # Connect to 573, fetching score
    try:
      url = 'https://www.ea-pass.konami.jp/contents/jubeat/ripples/play_mdata_list.do?fid=' + str(friend_id)
      result = urlfetch.fetch(url=url)
    except:
      logging.error('573 is down (songlist, urlfetch exception')
      return
    if result.status_code != 200:
      logging.error('573 is down (HTTP %d)' % result.status_code)
      return
    page_content = result.content
    if page_content.find('<div id="tune">') == -1:
      logging.warning('Score page down')
      return
    # Super-dirty but super-fast parsing
    player_name_match = re.search(r"<h4>([^<]+)さんの楽曲データ一覧<\/h4>", page_content)
    card_name = player_name_match.group(1)
    card_name = re.sub(r"\&nbsp\;", " ", card_name)
    
    find_result = re.findall(r"<td class\=\"score boderTop boderRight boderBottom (bgWhite01|bgBlue01)\">([0-9]+)<\/td>\s+<\/tr>", page_content)
    song_list = re.findall(r"<img src\=\"images\/player\_data\/music\_icon\/id([0-9]+)\.gif\"\s+\/>", page_content)
    best_score_total = 0
    ranker = rankingmodel.RankerList.gql('WHERE friend_id = :1', friend_id).get()
    if ranker is None:
      logging.error('Updater Error: Friend ID is not existed')
      return
    ranker.card_name = card_name # &nbsp; fixes hack
    ranker.songs_exc = 0
    ranker.songs_sss = 0
    ranker.songs_ss = 0
    ranker.songs_s = 0
    ranker.songs_a = 0
    ranker.songs_b = 0
    ranker.songs_c = 0
    del ranker.song_list[:]
    del ranker.song_scores[:]
    for item in song_list:
      ranker.song_list.append(long(item))
    for item in find_result:
      item_score = int(item[1])
      ranker.song_scores.append(item_score)
      if item_score > 700000: # C
        ranker.songs_c += 1
      if item_score > 800000: # B
        ranker.songs_b += 1
      if item_score > 850000: # A
        ranker.songs_a += 1
      if item_score > 900000: # S
        ranker.songs_s += 1
      if item_score > 950000: # SS
        ranker.songs_ss += 1
      if item_score > 980000: # SSS
        ranker.songs_sss += 1
      if item_score == 1000000: # EXC
        ranker.songs_exc += 1
      best_score_total += item_score

    # Register into DB
    ranker.tbs = tbs
    ranker.tbs_rank = tbs_rank
    ranker.score_average = best_score_total / len(find_result)
    ranker.last_updated = datetime.utcnow()
    ranker.put()
    # Purge memcache
    memcache.delete('mainpage')
    logging.info(str(card_name) + '(' + str(friend_id) + ')Updated.')

class UpdateRank(webapp.RequestHandler):
  def post(self):
    rankers = []
    query = rankingmodel.RankerList.gql('ORDER BY last_updated DESC LIMIT 250')
    rankers = query.fetch(250)
    r = GetRanker()
    scores = dict()
    num = 0
    for ranker in rankers:
      #if scores.has_key(str(ranker.friend_id)):
      #   self.response.out.write('%d' % ranker.friend_id)
      scores[str(ranker.friend_id)] =  [ranker.score_average]
      if len(scores) >= 20:
        r.SetScores(scores)
        num += len(scores)
        scores = dict()
    r.SetScores(scores)
    num += len(scores)
    logging.info('%d Ranks updated.' % num)

class UpdateRankAll(webapp.RequestHandler):
  def get(self):
    rankers = []
    query = rankingmodel.RankerList.gql('ORDER BY last_updated DESC LIMIT 1000')
    rankers = query.fetch(1000)
    r = GetRanker()
    scores = dict()
    num = 0
    for ranker in rankers:
      #if scores.has_key(str(ranker.friend_id)):
      #   self.response.out.write('%d' % ranker.friend_id)
      scores[str(ranker.friend_id)] =  [ranker.score_average]
      if len(scores) >= 20:
        r.SetScores(scores)
        num += len(scores)
        scores = dict()
    r.SetScores(scores)
    num += len(scores)
    memcache.delete('mainpage')
    logging.info('%d Ranks updated.' % num)

class MainHandler(webapp.RequestHandler):
  def get(self):
    rankers = []
    query = rankingmodel.RankerList.gql('ORDER BY last_updated ASC LIMIT 250')
    rankers = query.fetch(250)
    queue = taskqueue.Queue('score-updater')
    for ranker in rankers:
      queue.add(taskqueue.Task(url='/updater/update_user', params={'friend_id': ranker.friend_id, 'tbs': ranker.tbs}))
    queue.add(taskqueue.Task(url='/updater/update_rank'))

class FlushTBS(webapp.RequestHandler):
  def get(self):
    query = rankingmodel.RankerList.gql('ORDER BY last_updated DESC LIMIT 1000')
    rankers = query.fetch(1000)
    for ranker in rankers:
      ranker.tbs = 0
    db.put(rankers)
    self.response.out.write('Flush TBS OK')

def main():
  application = webapp.WSGIApplication([
                ('/updater/', MainHandler),
                ('/updater/flush_tbs', FlushTBS),
                ('/updater/update_user', UpdateUser),
                ('/updater/update_rank', UpdateRank),
                ('/updater/update_rank_all', UpdateRankAll)
                ],debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
