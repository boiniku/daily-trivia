"""Map approvals must never read or update ordinary trivia with the same ID."""
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util
import os
import unittest
from unittest.mock import MagicMock, patch

import test_workflow as fixtures
from trivia_photo.__main__ import parser
from trivia_photo.cloud_state import CloudState
from trivia_photo.config import Settings
from trivia_photo.database import Neon
from trivia_photo.storage import R2
from trivia_photo.workflow import Workflow

API = Path(os.environ['DAILY_TRIVIA_API_ROOT']) if os.environ.get('DAILY_TRIVIA_API_ROOT') else Path(__file__).resolve().parents[2] / '毎日雑学/apps/api'
ADMIN_AVAILABLE = all(importlib.util.find_spec(name) for name in ('streamlit', 'sqlalchemy', 'openai'))


class MapTargetTests(unittest.TestCase):
    def test_default_cli_and_existing_paths_stay_compatible(self):
        normal = Settings()
        self.assertEqual(parser().parse_args(['list']).target, 'normal')
        self.assertEqual(parser().parse_args(['--target', 'map', 'list']).target, 'map')
        self.assertEqual(normal.for_target('normal'), normal)
        mapped = normal.for_target('map')
        self.assertEqual(mapped.target_table, 'map_trivia')
        self.assertEqual(mapped.review_prefix, normal.review_prefix + '/map')
        self.assertEqual(mapped.publish_prefix, normal.publish_prefix + '/map')
        self.assertEqual(mapped.for_target('map'), mapped)
        with self.assertRaises(ValueError):
            normal.for_target('unknown')

    def test_shared_r2_does_not_mix_batches_or_attempted_ids(self):
        normal, mapped = fixtures.FakeStorage(), fixtures.FakeStorage()
        mapped.settings = normal.settings.for_target('map')
        mapped.documents = normal.documents
        row = fixtures.FakeNeon().rows[1]
        with TemporaryDirectory() as temp:
            ordinary = CloudState(normal, Path(temp) / 'normal')
            map_state = CloudState(mapped, Path(temp) / 'map')
            ordinary_batch = ordinary.create_batch([row])
            self.assertEqual(map_state.batch_ids(), [])
            self.assertEqual(map_state.attempted_ids(), [])
            map_batch = map_state.create_batch([row])
            self.assertEqual(ordinary.batch_ids(), [ordinary_batch])
            self.assertEqual(map_state.batch_ids(), [map_batch])
            with self.assertRaises(ValueError):
                map_state.get(ordinary_batch, 1)

    def test_workflow_uses_map_neon_table(self):
        settings = Settings().for_target('map')
        with patch('trivia_photo.workflow.Neon') as neon:
            Workflow(settings, MagicMock())
        neon.assert_called_once_with(settings.database_url, table='map_trivia')

    def test_map_writer_locks_and_updates_only_map_with_complete_sources(self):
        neon = Neon('postgresql+psycopg://test:unused@project.neon.tech/neondb', table='map_trivia')
        connection, cursor = MagicMock(), MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor
        cursor.__enter__.return_value = cursor
        row = dict(fixtures.FakeNeon().rows[1], image_urls=[])
        cursor.fetchone.return_value = row
        cursor.fetchall.return_value = [row]
        photos = [dict(url=f'https://images.test/map/{i}.webp', credit=f'Author {i}',
                       metadata={'source_url': f'https://commons.wikimedia.org/wiki/File:{i}.jpg',
                                 'license_url': 'https://creativecommons.org/licenses/by/4.0/'}) for i in (1, 2)]
        with patch.object(neon, 'connect', return_value=connection):
            neon.fetch(5, [1], [])
            neon.current(1)
            neon.publish_gallery(row, photos)
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any('public.trivia' in statement for statement in sql))
        self.assertTrue(any('AND is_active' in statement for statement in sql))
        self.assertTrue(any('public.map_trivia WHERE id = %s FOR UPDATE' in statement for statement in sql))
        writes = [call for call in cursor.execute.call_args_list if call.args[0].startswith('UPDATE')]
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0].args[0].startswith('UPDATE public.map_trivia SET'))
        values = writes[0].args[1]
        self.assertEqual(values[0], photos[0]['url'])
        self.assertEqual(values[1].adapted, [photo['url'] for photo in photos])
        for photo in photos:
            self.assertIn(photo['credit'], values[2].adapted[photo['url']])
            self.assertIn(photo['metadata']['license_url'], values[2].adapted[photo['url']])
        with self.assertRaises(ValueError):
            Neon('postgresql://test@project.neon.tech/neondb', table='trivia; DROP TABLE trivia')

    def test_map_publication_has_distinct_r2_key_for_same_id_and_hash(self):
        settings = Settings(endpoint='https://r2.test', access_key='test', secret_key='test',
                            bucket='public', review_bucket='review', public_base='https://images.test')
        item = {'trivia_id': 1, 'staging': {'bucket': 'review', 'key': 'review/source.webp'},
                'asset': {'sha256': 'a' * 64, 'size': 5}}
        head = {'ContentLength': 5, 'Metadata': {'sha256': 'a' * 64}}
        urls = []
        with patch('trivia_photo.storage.boto3.client'):
            for target in ('normal', 'map'):
                storage = R2(settings.for_target(target))
                with patch.object(storage, 'head', side_effect=[head, None, head]):
                    urls.append(storage.publish(item))
        self.assertNotEqual(*urls)
        self.assertIn('/auto/map/1-', urls[1])

    @unittest.skipUnless(ADMIN_AVAILABLE and (API / 'admin_dashboard.py').is_file(), 'Optional sibling Streamlit admin environment')
    def test_admin_scope_switch_clears_normal_cache_and_approval_writes_only_map(self):
        import sys
        import test_approval as approval
        from streamlit.testing.v1 import AppTest
        api = API
        sys.path.insert(0, str(api))
        self.addCleanup(lambda: sys.path.remove(str(api)))
        original = approval.ApprovalTests('test_adoption_still_waits_for_credit_display')
        original.setUp()
        self.addCleanup(original.tearDown)
        mapped_storage = fixtures.FakeStorage()
        mapped_storage.settings = original.storage.settings.for_target('map')
        mapped_storage.documents = original.storage.documents
        mapped_storage.objects = original.storage.objects
        map_neon = fixtures.FakeNeon()
        map_neon.rows[1]['title'] = 'Mapだけの写真'
        mapped = Workflow(mapped_storage.settings,
                          CloudState(mapped_storage, Path(original.temp.name) / 'map'),
                          map_neon, approval.VariantCommons(), mapped_storage)
        batch = mapped.collect(1)['batch']
        fixtures.stage_fixture(mapped, batch, 1)
        def create(*, database_url, target):
            from database import DATABASE_URL
            self.assertTrue(database_url == DATABASE_URL)
            return mapped if target == 'map' else original.workflow
        with patch('trivia_photo.admin_ui.create_workflow', side_effect=create) as factory:
            app = AppTest.from_string('from services.photo_review import render_photo_review\nrender_photo_review()', default_timeout=20)
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state['photo_document']['batch'], original.batch)
            app.text_input(key='photo_query').set_value('題材1').run()
            app.radio(key='photo_review_target').set_value('雑学MAP').run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.text_input(key='photo_query').value, '')
            self.assertEqual(app.session_state['photo_document']['batch'], batch)
            self.assertEqual(factory.call_args.kwargs['target'], 'map')
            self.assertEqual(map_neon.writes, [])
            choices = [box for box in app.checkbox if box.label == 'この写真を採用する']
            choices[1].check().run()
            next(box for box in app.checkbox if box.label == '写真と写っている対象の利用条件を確認した').check()
            next(button for button in app.button if button.label == '選択した写真を採用して本番へ反映').click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(mapped.state.get(batch, 1)['status'], 'published')
            self.assertEqual(len(map_neon.rows[1]['image_urls']), 2)
            self.assertEqual(original.neon.writes, [])
            self.assertEqual(original.state.get(original.batch, 1)['status'], 'staged')
            app.radio(key='photo_review_target').set_value('通常の雑学').run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state['photo_document']['batch'], original.batch)
            self.assertEqual(factory.call_args.kwargs['target'], 'normal')
