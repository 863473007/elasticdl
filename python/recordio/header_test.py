import unittest
import os
import shutil
from recordio.header import *


class TestHeader(unittest.TestCase):
    """ Test header.py
    """

    def setUp(self):
        if not os.path.exists('/tmp/elasticdl'):
            os.mkdir('/tmp/elasticdl')
        if not os.path.exists('/tmp/elasticdl/recordio'):
            os.mkdir('/tmp/elasticdl/recordio')

    def tearDown(self):
        if os.path.exists('/tmp/elasticdl/recordio'):
            shutil.rmtree('/tmp/elasticdl/recordio')

    def test_write_and_parse(self):
        num_records = 1000
        checksum = 824863398
        compressor = Compressor.gzip
        compress_size = 10240
        file_name = '/tmp/elasticdl/recordio/test_header'

        tmp_file = open(file_name, 'wb')
        header1 = Header(num_records, checksum, compressor, compress_size)
        header1.write(tmp_file)
        tmp_file.close()

        tmp_file = open(file_name, 'rb')
        header2 = Header()
        header2.parse(tmp_file, 0)
        tmp_file.close()

        self.assertEqual(num_records, header2.total_count())
        self.assertEqual(checksum, header2.checksum())
        self.assertEqual(compressor, header2.compressor())
        self.assertEqual(compress_size, header2.compress_size())

        # os.remove(file_name)


if __name__ == '__main__':
    unittest.main()
