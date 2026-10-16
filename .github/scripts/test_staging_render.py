import unittest

from staging_render import NAME, URL, validate


class StagingIsolationTests(unittest.TestCase):
    def setUp(self):
        self.service = dict(name=NAME, id='staging', type='web_service', branch='develop',
                            repo='https://github.com/boiniku/daily-trivia', serviceDetails=dict(url=URL))

    def test_exact_staging_service_is_accepted(self):
        validate(self.service, 'production')

    def test_production_and_other_targets_are_rejected(self):
        for key, value in [('id', 'production'), ('name', 'production'), ('branch', 'main'),
                           ('repo', 'https://github.com/other/repo'),
                           ('serviceDetails', dict(url='https://daily-trivia-e7ge.onrender.com'))]:
            with self.subTest(field=key), self.assertRaises(ValueError):
                validate(dict(self.service, **{key: value}), 'production')


if __name__ == '__main__':
    unittest.main()
