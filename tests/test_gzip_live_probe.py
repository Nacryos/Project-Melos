import gzip
import pytest
from scripts.check_gzip_live import verify_pair


def pair():
    data = b'{"data":"' + b'x' * 5000 + b'"}'
    zipped = gzip.compress(data)
    return ({'status': 200, 'headers': {'content-length': str(len(data)), 'vary': 'Accept-Encoding'}, 'body': data},
            {'status': 200, 'headers': {'content-length': str(len(zipped)), 'vary': 'Origin, Accept-Encoding',
                                      'content-encoding': 'gzip'}, 'body': zipped})


def test_exact_transport():
    assert verify_pair(*pair())['byte_exact']


@pytest.mark.parametrize('change', ['body', 'length', 'vary'])
def test_reject_transport_corruption(change):
    plain, zipped = pair()
    if change == 'body':
        plain['body'] = plain['body'].replace(b'x', b'y')
    elif change == 'length':
        zipped['headers']['content-length'] = '1'
    else:
        plain['headers']['vary'] = 'Origin'
    with pytest.raises(AssertionError):
        verify_pair(plain, zipped)
