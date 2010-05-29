from google.appengine.ext import db
from ranker import ranker
from google.appengine.api import datastore
from google.appengine.api import datastore_errors
from google.appengine.api import datastore_types

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
class RankerList(db.Model):
  friend_id = db.IntegerProperty(required=True)
  card_name = db.StringProperty(default='')
  score_average = db.IntegerProperty(default=0)
  songs_exc = db.IntegerProperty(default=0)
  songs_sss = db.IntegerProperty(default=0)
  songs_ss = db.IntegerProperty(default=0)
  songs_s = db.IntegerProperty(default=0)
  songs_a = db.IntegerProperty(default=0)
  songs_b = db.IntegerProperty(default=0)
  songs_c = db.IntegerProperty(default=0)
  tbs = db.IntegerProperty(default=0)
  tbs_rank = db.IntegerProperty(default=0)
  last_updated = db.DateTimeProperty()
  song_list = db.ListProperty(long,indexed=False)
  song_scores = db.ListProperty(long,indexed=False)
