'''
Created on Oct 25, 2012

@author: jluker
'''

import os
import sys
import site
site.addsitedir(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) #@UndefinedVariable

import pytz
import tempfile
import unittest2
import subprocess
from stat import *
from time import sleep
from datetime import datetime, timedelta
from mongoalchemy import fields

from config import config
from adsdata import models, utils, session

class BasicCollection(models.DataFileCollection):
    config_collection_name = 'adsdata_test'
    foo = fields.StringField(_id=True)
    bar = fields.IntField()
    field_order = [foo, bar]
    
class NamedRestKeyCollection(models.DataFileCollection):
    config_collection_name = 'adsdata_test'
    foo = fields.StringField(_id=True)
    bar = fields.IntField()
    baz = fields.ListField(fields.StringField())
    restkey = 'baz'
    field_order = [foo, bar]
    
class AggregatedCollection(models.DataFileCollection):
    config_collection_name = 'adsdata_test'
    foo = fields.StringField(_id=True)
    bar = fields.ListField(fields.StringField())
    aggregated = True
    field_order = [foo, bar]
    
class AdsdataTestCase(unittest2.TestCase):
    
    def setUp(self):
        config.MONGO_DATABASE = 'test'
        config.MONGO_HOST = 'localhost'
        self.session = utils.get_session()
        self.session.drop_database('test')
        
    def load_test_data(self):
        test_data_dir = os.path.join(os.path.dirname(__file__), 'demo_data')
        for f in os.listdir(test_data_dir):
            abs_path = os.path.join(test_data_dir, f)
            collection_name = os.path.splitext(f)[0]
            with open(os.devnull, "w") as fnull:
                subprocess.call(["mongoimport", "--drop",
                                 "-d", "test", 
                                 "-c", collection_name, 
                                 "-h", "%s:%d" % (config.MONGO_HOST, config.MONGO_PORT),
                                 abs_path]) #, stdout=fnull)    
                
    def tearDown(self):
        self.session.drop_database('test')
    
class TestDataCollection(AdsdataTestCase):
    
    def test_last_synced(self):
        self.assertTrue(BasicCollection.last_synced(self.session) is None, 'No previous DLT == last_synced() is None')
        
        now = datetime(2000,1,1).replace(tzinfo=pytz.utc)
        dlt = models.DataLoadTime(collection='adsdata_test', last_synced=now)
        self.session.insert(dlt)
        self.assertTrue(BasicCollection.last_synced(self.session) == now, 'last_synced() returns correct DLT')
        
    def test_last_modified(self):
        tmp = tempfile.NamedTemporaryFile()
        config.MONGO_DATA_COLLECTIONS['adsdata_test'] = tmp.name
        tmp_modified = datetime.fromtimestamp(os.stat(tmp.name)[ST_MTIME]).replace(tzinfo=pytz.utc)
        last_modified = BasicCollection.last_modified()
        del config.MONGO_DATA_COLLECTIONS['adsdata_test']
        self.assertTrue(last_modified == tmp_modified, 'last_modfied() returns correct mod time')
        
    def test_needs_sync(self):
        tmp = tempfile.NamedTemporaryFile()
        config.MONGO_DATA_COLLECTIONS['adsdata_test'] = tmp.name
        self.assertTrue(BasicCollection.needs_sync(self.session), 'No DLT == needs sync')
        
        # sleep for a moment to ensure new last synced time is older than temp file
        sleep(0.1) 
        now = datetime.now()
        dlt = models.DataLoadTime(collection='adsdata_test', last_synced=now)
        self.session.insert(dlt)
        self.assertFalse(BasicCollection.needs_sync(self.session), 'DLT sync time > file mod time == does not need sync')
        
        dlt.last_synced = now - timedelta(days=1)
        self.session.update(dlt)
        self.assertTrue(BasicCollection.needs_sync(self.session), 'DLT sync time < file mod time == needs sync')
        
    def test_load_data(self):
        tmp = tempfile.NamedTemporaryFile()
        config.MONGO_DATA_COLLECTIONS['adsdata_test'] = tmp.name
        for triplet in zip("abcd","1234","wxyz"):
            print >>tmp, "%s\t%s\t%s" % triplet
        tmp.flush()
        self.assertTrue(BasicCollection.last_synced(self.session) is None)
        BasicCollection.load_data(self.session)
        self.assertTrue(type(BasicCollection.last_synced(self.session)) == datetime, 'load data creates DLT entry')
        self.assertEqual(self.session.query(BasicCollection).count(), 4, 'all records loaded')
        
    def test_restkey(self):
        tmp = tempfile.NamedTemporaryFile()
        config.MONGO_DATA_COLLECTIONS['adsdata_test'] = tmp.name
        for triplet in zip("abcd","1234","wxyz"):
            print >>tmp, "%s\t%s\t%s" % triplet
        tmp.flush()
        BasicCollection.restkey = "unwanted"
        BasicCollection.load_data(self.session, source_file=tmp.name)
        entry_a = self.session.query(BasicCollection).filter(BasicCollection.foo == 'a').first()
        self.assertFalse(hasattr(entry_a, 'baz'))
        
    def test_named_restkey(self):
        tmp = tempfile.NamedTemporaryFile()
        config.MONGO_DATA_COLLECTIONS['adsdata_test'] = tmp.name
        for quad in zip("abcd","1234","wxyz", "5678"):
            print >>tmp, "%s\t%s\t%s\t%s" % quad
        tmp.flush()
        NamedRestKeyCollection.load_data(self.session, source_file=tmp.name)
        entry_a = self.session.query(NamedRestKeyCollection).filter(NamedRestKeyCollection.foo == 'a').first()
        self.assertEqual(entry_a.baz, ["w", "5"])
        
    def test_load_data_aggregated(self):
        tmp = tempfile.NamedTemporaryFile()
        config.MONGO_DATA_COLLECTIONS['adsdata_test'] = tmp.name
        for pair in zip("aabbccdd","12345678"):
            print >>tmp, "%s\t%s" % pair
        tmp.flush()
        AggregatedCollection.load_data(self.session)
        self.assertEqual(self.session.query(AggregatedCollection).count(), 0, 'no records loaded in the actual collection')
        self.assertEqual(self.session.get_collection('adsdata_test_load').count(), 8, 'all records loaded in "_load" collection')
        
        utils.map_reduce_listify(self.session, self.session.get_collection('adsdata_test_load'), 'adsdata_test', 'load_key', 'bar')
        self.assertEqual(self.session.query(AggregatedCollection).count(), 4, 'map-reduce loaded ')
        entry_a = self.session.query(AggregatedCollection).filter(AggregatedCollection.foo == 'a').first()
        self.assertTrue(entry_a is not None)
        self.assertEqual(entry_a.bar, ["1","2"])
        
    def test_coerce_types(self):
        
        class CoerceCollection(models.DataFileCollection):
            foo = fields.StringField()
            bar = fields.IntField()
            
        class CoerceCollection2(models.DataFileCollection):
            foo = fields.FloatField()
            bar = fields.ListField(fields.StringField())
        
        class CoerceCollection3(models.DataFileCollection):
            foo = fields.ListField(fields.IntField())
            bar = fields.SetField(fields.FloatField())
            
        recs = [(BasicCollection, {"foo": "a", "bar": "3"}, {"foo": "a", "bar": 3}), # bar's str -> int
                (BasicCollection, {"foo": 1, "bar": "3"}, {"foo": 1, "bar": 3}), # foo's str ignored; bar's str -> int
                (BasicCollection, {"foo": "a", "bar": 3}, {"foo": "a", "bar": 3}), # bar's int preserved
                (AggregatedCollection, {"foo": "a", "bar": ["1","2"]}, {"foo": "a", "bar": ["1","2"]}), # bar's list of str ignored
                (CoerceCollection, {"foo": "a", "bar": "3"}, {"foo": "a", "bar": 3}), # bar's str -> int
                (CoerceCollection2, {"foo": "1.1234", "bar": ["a","b"]}, {"foo": 1.1234, "bar": ["a","b"]}), # foo's str -> float; bar's list of str ignored
                (CoerceCollection2, {"foo": "2", "bar": [1,2]}, {"foo": 2.0, "bar": [1,2]}), # foo's str > float; bar's list of int ignored
                (CoerceCollection3, {"foo": ["1", "2"], "bar": ["1.1234", "2"]}, {"foo": [1,2], "bar": [1.1234, 2.0]})
                ]
        for cls, rec, expected in recs:
            cls.coerce_types(rec)
            self.assertEqual(rec, expected)

class TestDocs(AdsdataTestCase):        
    
    def test_generate_doc(self):
        pass
    
    def test_dt_manipulator(self):
        self.session = utils.get_session(inc_manipulators=False)
        self.session.add_manipulator(session.DatetimeInjector('ads_test'))
        collection = self.session.get_collection('ads_test')
        collection.insert({"foo": 1})
        entry = collection.find_one({"foo": 1}, manipulate=False)
        self.assertTrue(entry.has_key('_dt'))
        self.assertTrue(isinstance(entry['_dt'], datetime))
        # let the manipulator remove the _dt
        entry = collection.find_one({"foo": 1})
        self.assertFalse(entry.has_key('_dt'))
        
        # make sure that no '_dt' values are preserved
        dt = datetime.utcnow().replace(tzinfo=pytz.utc)
        collection.insert({"foo": 1, '_dt': dt})
        entry = collection.find_one({"foo": 1}, manipulate=False)
        self.assertNotEqual(dt, entry['_dt'])
        
    def test_digest_manipulator(self):
        self.session = utils.get_session(inc_manipulators=False)
        self.session.add_manipulator(session.DigestInjector('ads_test'))
        collection = self.session.get_collection('ads_test')
        collection.insert({"foo": 1})
        entry = collection.find_one({"foo": 1}, manipulate=False)
        self.assertTrue(entry.has_key('_digest'))
        
        digest = session.doc_digest({"bar": 1}, self.session.db)
        collection.insert({"baz": 1, "_digest": digest})
        entry = collection.find_one({"baz": 1}, manipulate=False)
        self.assertEqual(entry['_digest'], digest)
        
    def test_dereference_manipulator(self):
        from bson import DBRef
        self.session = utils.get_session(inc_manipulators=False)
        collection_a = self.session.get_collection('test_a')
        collection_b = self.session.get_collection('test_b')
        collection_a.insert({"_id": 1, "foo": "bar"})
        collection_b.insert({"baz": "blah", "foo": DBRef(collection="test_a", id=1)})
        manipulator = session.DereferenceManipulator(ref_fields=[('test_b', 'foo')])
        self.session.add_manipulator(manipulator)
        doc = collection_b.find_one({"baz": "blah"})
        self.assertEqual(doc['foo'], 'bar')
        
    def test_fetch_doc(self):
        self.load_test_data()
        doc = self.session.get_doc("2012ASPC..461..837L")
        self.assertIsNotNone(doc)
        # _dt datestamp should be removed by manipulator
        self.assertNotIn("_dt", doc)
        
        # now get the doc again but retaining the _dt field
        doc = self.session.get_doc("2012ASPC..461..837L", manipulate=False)
        self.assertIn("_dt", doc)
        
    def test_store_doc(self):
        new_doc = {"bibcode": "2000abcd..123..456A", "foo": "bar"}
        digest = session.doc_digest(new_doc, self.session.db)
        self.session.store_doc(new_doc)
        stored_doc = self.session.get_doc(new_doc['bibcode'], manipulate=False)
        self.assertIn("_digest", stored_doc)
        self.assertIn("_dt", stored_doc)
        self.assertEqual(stored_doc['_digest'], digest)
        
    def test_modify_existing_doc(self):
        self.load_test_data()
        existing_doc = self.session.get_doc("1999abcd.1234..111Q", manipulate=False)
        existing_digest = existing_doc['_digest']
        existing_dt = existing_doc['_dt']
        del existing_doc['_digest']
        del existing_doc['_dt']
        existing_doc['abcd'] = 1234
        new_digest = session.doc_digest(existing_doc, self.session.db)
        self.session.store_doc(existing_doc)
        modified_doc = self.session.get_doc("1999abcd.1234..111Q", manipulate=False)
        self.assertEqual(modified_doc['_digest'], new_digest)
        self.assertNotEqual(modified_doc['_digest'], existing_digest)
        self.assertNotEqual(modified_doc['_dt'], existing_dt)
        
    def test_unmodified_existing_doc(self):
        self.load_test_data()
        existing_doc = self.session.get_doc("1999abcd.1234..111Q", manipulate=False)
        existing_digest = existing_doc['_digest']
        existing_dt = existing_doc['_dt']
        del existing_doc['_digest']
        del existing_doc['_dt']
        new_digest = session.doc_digest(existing_doc, self.session.db)
        self.session.store_doc(existing_doc)
        unmodified_doc = self.session.get_doc("1999abcd.1234..111Q", manipulate=False)
        self.assertEqual(new_digest, unmodified_doc['_digest'])
        self.assertEqual(existing_digest, unmodified_doc['_digest'])
        # datetime value should not have been updated
        self.assertEqual(existing_dt, unmodified_doc['_dt'])
        
        
    
if __name__ == '__main__':
    unittest2.main()