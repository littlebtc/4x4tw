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

class AddUser(webapp.RequestHandler):
  def post(self):
    webapp.template.register_template_library('templatetags.spacify')    
    friend_id = self.request.get('friend_id','')
    try:
      friend_id = long(friend_id)
    except:
      self.response.out.write('請輸入整數 Q____Q')
      return
    
    # Check update time I
    if datetime.utcnow().hour >= 19 or datetime.utcnow().hour < 1:
      self.response.out.write('您無法在 UTC 時間 19:00 至 01:00 期間實行手動更新。（這是台灣時間 03:00 至 09:00，日本時間 04:00 至 10:00。）')
      return
    # Check update time II
    ranker = rankingmodel.RankerList.gql('WHERE friend_id = :1', friend_id).get()
    if ranker is not None and ranker.last_updated:
      time_diff = datetime.utcnow() - ranker.last_updated
      if time_diff.days == 0 and time_diff.seconds < 900:
        self.response.out.write('您無法在15分鐘之內重複進行更新。')
        return
       
    # Connect to 573, checking player location
    try:
      url = 'https://www.ea-pass.konami.net/contents/jubeat/ripples/play_top.do?fid=' + str(friend_id)
      result = urlfetch.fetch(url=url)
    except:
      self.response.out.write('573 is down!')
      logging.warning('573 is down (urlfetch exception)')
      return
    if result.status_code != 200:
      self.response.out.write('573 is down!')
      logging.warning('573 is down (HTTP %d)' % result.status_code)
      return
    page_content = result.content
    if page_content.find('error') > -1 or page_content.find('<div id="playerNameBox">') == -1:
      self.response.out.write('發生問題。請確定您輸入的是正確的朋友ID / 或著現在573在維修。')
      return
    tbs_rank_match = re.search("<h5>([0-9]+)[^0-9<]*([0-9]+)位<\/h5>", page_content, re.UNICODE)
    if tbs_rank_match is None:
      if ranker is not None:
        r = GetRanker()
        r.SetScore(str(friend_id), None)
        ranker.delete()
        self.response.out.write('玩家資料為非公開，已將採計過的成績刪除。')
        return
      else:
        self.response.out.write('玩家資料為非公開，無法採計 :(。')
        return
    tbs = int(tbs_rank_match.group(1))
    tbs_rank = int(tbs_rank_match.group(2))
    if page_content.find('台湾') == -1:
      self.response.out.write('就跟你講台灣限定了咩 >"< / Please enter player whose last played area is Taiwan.')
      return
    # If tbs is not updated, do nothing
    if ranker is not None:
      if ranker.tbs == tbs:
        ranker.last_updated = datetime.utcnow()
        ranker.put()
        r = GetRanker()
        rank = r.FindRank([ranker.score_average])
        #self.response.out.write('<p>玩家資料已經採計（成績未刷新）。</p><p><a href="/ju/">回到排行表</a></p>')
        path = os.path.join(os.path.dirname(__file__), 'update.htm')
        result = template.render(path, {'friend_id': friend_id, 'card_name': ranker.card_name, 'rank': rank + 1})
        self.response.out.write(result)
        return
    #time.sleep(1)
    # Connect to 573, fetching score
    try:
      url = 'https://www.ea-pass.konami.net/contents/jubeat/ripples/play_mdata_list.do?fid=' + str(friend_id)
      result = urlfetch.fetch(url=url)
    except:
      self.response.out.write('573 is down!')
      return
    if result.status_code != 200:
      self.response.out.write('573 is down!')
      return
    page_content = result.content
    if page_content.find('<div id="tune">') == -1:
      self.response.out.write('拿取成績頁面時發生問題。請通知管理者。')
      return
    # Super-dirty but super-fast parsing
    player_name_match = re.search(r"<h4>([^<]+)さんの楽曲データ一覧<\/h4>", page_content)
    card_name = player_name_match.group(1)
    card_name = re.sub(r"\&nbsp\;", " ", card_name)
    find_result = re.findall(r"<td class\=\"score boderTop boderRight boderBottom (bgWhite01|bgBlue01)\">([0-9]+)<\/td>\s+<\/tr>", page_content)
    song_list = re.findall(r"<img src\=\"images\/player\_data\/music\_icon\/id([0-9]+)\.gif\"\s+\/>", page_content)
    best_score_total = 0
    if ranker is None:
      ranker = rankingmodel.RankerList(
        friend_id = friend_id,
        card_name = card_name,
      )
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
    r = GetRanker()
    r.SetScore(str(friend_id), [ranker.score_average])
    rank = r.FindRank([ranker.score_average])
    # Purge memcache
    memcache.delete('mainpage')
    # Result
    path = os.path.join(os.path.dirname(__file__), 'update.htm')
    result = template.render(path, {'friend_id': friend_id, 'card_name': ranker.card_name, 'rank': rank + 1})
    self.response.out.write(result)
    #self.response.out.write('<p>玩家資料已經採計。</p><p><a href="/ju/">回到排行表</a></p>')

class MainHandler(webapp.RequestHandler):

  def get(self):
    webapp.template.register_template_library('templatetags.spacify')    
    rank_start = 1
    path = os.path.join(os.path.dirname(__file__), 'main.htm')
    # Use memcache
    memcache_data = memcache.get('mainpage')
    if memcache_data is None or self.request.get('flush'):
      # Get data lag
      oldest_data = rankingmodel.RankerList.gql('ORDER BY last_updated ASC LIMIT 1').get()
      data_lag = 0
      if oldest_data is not None:
        if oldest_data.last_updated:
          time_diff = datetime.utcnow() - oldest_data.last_updated
          data_lag = time_diff.days
      # Get rank 
      rankers = []
      query = rankingmodel.RankerList.gql('ORDER BY score_average DESC LIMIT 100')
      rankers = query.fetch(100)
      # Process rank
      for i in range(len(rankers)):
        if i > 0 and rankers[i].score_average == rankers[i-1].score_average:
          rankers[i].rank = rankers[i-1].rank
        else:
          rankers[i].rank = rank_start + i
      result = template.render(path, {'rankers': rankers, 'data_lag': data_lag})
      if not memcache.add('mainpage', result, 86400):
        logging.error('Memcache error!')
    else: 
      result = memcache_data
    self.response.out.write(result)

class ShowScores(webapp.RequestHandler):
  def get(self):
    friend_id = self.request.get('friend_id','')
    try:
      friend_id = long(friend_id)
    except:
      self.response.out.write('請輸入整數 Q____Q')
      return
    my_dict = common.GetSongDict()
    ranker = rankingmodel.RankerList.gql('WHERE friend_id = :1', friend_id).get()
    if ranker is None:
      self.response.out.write('沒這個人喔')
      return
    self.response.out.write('應當顯示正確的紅譜分數。如有錯誤敬請回報！<table><tr><th>Song</th><th>Score</th></tr>')
    for i in range(len(ranker.song_list)):
      self.response.out.write('<tr><td>'+my_dict[ranker.song_list[i]]+'</td><td>'+str(ranker.song_scores[i])+'</td></tr>')      
    self.response.out.write('</table>')

def main():
  application = webapp.WSGIApplication([
                ('/ju/', MainHandler),
                ('/ju/test', ShowScores),
                ('/ju/add', AddUser)
                ],debug=True)
  util.run_wsgi_app(application)


if __name__ == '__main__':
  main()
