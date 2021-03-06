"""Test cases for http.py.

These tests are designed to mock http responses from the IPFS daemon. They
are used to determine if the functions in http.py are operating correctly.

Classes:
TestHttp -- A TCP client for interacting with an IPFS daemon
"""

import json
import socket
import time

import pytest
import pytest_localserver.http

import ipfshttpclient.http_common
import ipfshttpclient.http
import ipfshttpclient.exceptions



@pytest.fixture(scope="module")
def http_server(request):
	"""
	Slightly modified version of the ``pytest_localserver.plugin.http_server``
	fixture that will only start and stop the server application once for test
	performance reasons.
	"""
	server = pytest_localserver.http.ContentServer()
	server.start()
	request.addfinalizer(server.stop)
	return server


@pytest.fixture
def http_client(http_server):
	return ipfshttpclient.http.ClientSync(
		"/ip4/{0}/tcp/{1}/http".format(*http_server.server_address),
		ipfshttpclient.DEFAULT_BASE
	)


def broken_http_server_app(environ, start_response):
	"""
	HTTP server application that will be slower to respond (0.5 seconds)
	"""
	start_response("0 What the heck?", [])
	
	yield b""

@pytest.fixture(scope="module")
def broken_http_server(request):
	server = pytest_localserver.http.WSGIServer(application=broken_http_server_app)
	server.start()
	request.addfinalizer(server.stop)
	return server


def slow_http_server_app(environ, start_response):
	"""
	HTTP server application that will be slower to respond (0.5 seconds)
	"""
	start_response("400 Bad Request", [
		("Content-Type", "text/json")
	])
	
	time.sleep(0.5)
	yield json.dumps({
		"Type": "error",
		"Message": "Timeout was not triggered"
	}).encode("utf-8")

@pytest.fixture(scope="module")
def slow_http_server(request):
	server = pytest_localserver.http.WSGIServer(application=slow_http_server_app)
	server.start()
	request.addfinalizer(server.stop)
	return server


def test_successful_request(http_client, http_server):
	"""Tests that a successful http request returns the proper message."""
	http_server.serve_content("okay", 200)
	
	res = http_client.request("/okay")
	assert res == b"okay"

def test_generic_failure(http_client, http_server):
	"""Tests that a failed http request raises an HTTPError."""
	http_server.serve_content("fail", 500)
	
	with pytest.raises(ipfshttpclient.exceptions.StatusError):
		http_client.request("/fail")

def test_http_client_failure(http_client, http_server):
	"""Tests that an http client failure raises an ipfsHTTPClientError."""
	http_server.serve_content(json.dumps({
		"Message": "Someone set us up the bomb"
	}), 500)
	
	with pytest.raises(ipfshttpclient.exceptions.ErrorResponse):
		http_client.request("/http_client_fail")

def test_http_client_failure_broken_msg(http_client, http_server):
	"""Tests that an http client failure raises an ipfsHTTPClientError."""
	http_server.serve_content("Message: This isn't JSON", 500)
	
	with pytest.raises(ipfshttpclient.exceptions.StatusError):
		http_client.request("/http_client_fail")

def test_http_client_late_failure(http_client, http_server):
	"""Tests that an http client failure raises an ipfsHTTPClientError."""
	http_server.serve_content(json.dumps({
		"Message": "okay"
	}) + "\n" + json.dumps({
		"Type":    "error",
		"Message": "request failed after all"
	}), 200)
	
	with pytest.raises(ipfshttpclient.exceptions.PartialErrorResponse):
		http_client.request("/http_client_fail_late", decoder="json")

def test_stream(http_client, http_server):
	"""Tests that the stream flag being set returns the raw response."""
	http_server.serve_content("okay", 200)
	
	res = http_client.request("/okay", stream=True)
	assert next(res) == b"okay"
	
	# Check iterator fuse
	with pytest.raises(StopIteration):
		next(res)
	with pytest.raises(StopIteration):
		next(res)
	with pytest.raises(StopIteration):
		next(res)

def test_cat(http_client, http_server):
	"""Tests that paths ending in /cat are not parsed."""
	http_server.serve_content(json.dumps({
		"Message": "do not parse"
	}), 200)
	
	res = http_client.request("/cat")
	assert res == b'{"Message": "do not parse"}'

def test_default_decoder(http_client, http_server):
	"""Tests that the default encoding is set to json."""
	http_server.serve_content(json.dumps({
		"Message": "okay"
	}), 200)
	
	res = http_client.request("/http_client_okay")
	assert res == b'{"Message": "okay"}'

def test_explicit_decoder(http_client, http_server):
	"""Tests that an explicit decoder is handled correctly."""
	http_server.serve_content(json.dumps({
		"Message": "okay"
	}), 200)
	
	res = http_client.request("/http_client_okay", decoder="json")
	assert res[0]["Message"] == "okay"

def test_unsupported_decoder(http_client, http_server):
	"""Tests that unsupported encodings raise an exception."""
	http_server.serve_content(json.dumps({
		"Message": "Someone set us up the bomb"
	}), 500)
	
	with pytest.raises(ipfshttpclient.exceptions.EncoderMissingError):
		http_client.request("/http_client_fail", decoder="xyz")

def test_failed_decoder(http_client, http_server):
	"""Tests that a failed encoding parse raises an exception."""
	http_server.serve_content("okay", 200)
	
	with pytest.raises(ipfshttpclient.exceptions.DecodingError):
		http_client.request("/okay", decoder="json")

"""TODO: Test successful download
Need to determine correct way to mock an http request that returns a tar
file. tarfile.open expects the tar to be in the form of an octal escaped
string, but internal functionality keeps resulting in hexadecimal.
"""

def test_failed_download(http_client, http_server):
	"""Tests that a failed download raises an HTTPError."""
	http_server.serve_content("fail", 500)
	
	with pytest.raises(ipfshttpclient.exceptions.StatusError):
		http_client.download("/fail")

def test_download_connect_error():
	"""Tests that a download from a non-existing server raises a ConnectionError."""
	http_client = ipfshttpclient.http.ClientSync(
		"/ip4/127.4.5.6/tcp/12393/http",
		ipfshttpclient.DEFAULT_BASE
	)
	
	with pytest.raises(ipfshttpclient.exceptions.ConnectionError):
		http_client.download('/any')

def test_download_protocol_error(broken_http_server):
	"""Tests that a download from a server violating the HTTP protocol raises a ProtocolError."""
	http_client = ipfshttpclient.http.ClientSync(
		"/ip4/{0}/tcp/{1}/http".format(*broken_http_server.server_address),
		ipfshttpclient.DEFAULT_BASE
	)
	
	with pytest.raises(ipfshttpclient.exceptions.ProtocolError):
		http_client.download('/any')

def test_download_timeout(slow_http_server):
	"""Tests that a timed-out download raises a TimeoutError."""
	http_client = ipfshttpclient.http.ClientSync(
		"/ip4/{0}/tcp/{1}/http".format(*slow_http_server.server_address),
		ipfshttpclient.DEFAULT_BASE
	)
	
	with pytest.raises(ipfshttpclient.exceptions.TimeoutError):
		http_client.download('/timeout', timeout=0.1)

def test_request_connect_error():
	"""Tests that a request to a non-existing server raises a ConnectionError."""
	http_client = ipfshttpclient.http.ClientSync(
		"/ip4/127.99.99.99/tcp/12393/http",
		ipfshttpclient.DEFAULT_BASE
	)
	
	with pytest.raises(ipfshttpclient.exceptions.ConnectionError):
		http_client.download('/any')

def test_request_protocol_error(broken_http_server):
	"""Tests that a download from a server violating the HTTP protocol raises a ProtocolError."""
	http_client = ipfshttpclient.http.ClientSync(
		"/ip4/{0}/tcp/{1}/http".format(*broken_http_server.server_address),
		ipfshttpclient.DEFAULT_BASE
	)
	
	with pytest.raises(ipfshttpclient.exceptions.ProtocolError):
		http_client.request('/any')

def test_request_timeout(slow_http_server):
	"""Tests that a timed-out request raises a TimeoutError."""
	http_client = ipfshttpclient.http.ClientSync(
		"/ip4/{0}/tcp/{1}/http".format(*slow_http_server.server_address),
		ipfshttpclient.DEFAULT_BASE
	)
	
	with pytest.raises(ipfshttpclient.exceptions.TimeoutError):
		http_client.request('/timeout', timeout=0.1)

def test_session(http_client, http_server):
	"""Tests that a session is established and then closed."""
	http_server.serve_content("okay", 200)
	
	assert http_client._session is None
	try:
		http_client.open_session()
		http_client._session is not None
		res = http_client.request("/okay")
		assert res == b"okay"
	finally:
		# Closing the session several times should be fine
		http_client.close_session()
		http_client.close_session()
		http_client.close_session()
	assert http_client._session is None


def test_stream_close(mocker, http_client, http_server):
	mocker.patch("ipfshttpclient.http_common._notify_stream_iter_closed")
	http_server.serve_content("okay", 200)
	
	with http_client.request("/okay", stream=True) as response_iter:
		assert ipfshttpclient.http_common._notify_stream_iter_closed.call_count == 0
	assert ipfshttpclient.http_common._notify_stream_iter_closed.call_count == 1
	
	response_iter = http_client.request("/okay", stream=True)
	assert ipfshttpclient.http_common._notify_stream_iter_closed.call_count == 1
	response_iter.close()
	assert ipfshttpclient.http_common._notify_stream_iter_closed.call_count == 2
	
	http_client.request("/okay")
	assert ipfshttpclient.http_common._notify_stream_iter_closed.call_count == 4


def test_basic_auth(http_client, http_server):
	http_server.serve_content("okay", 200)
	del http_server.requests[:]
	
	http_client.request("/okay", auth=("hallo", "welt"))
	
	request_auth = http_server.requests[0].authorization
	assert request_auth.username == "hallo" and request_auth.password == "welt"


def generator():
	yield b"abcdef"
	yield b""
	yield b"()[]{}+++"

class Wrapper:
	def __init__(self, obj):
		self._obj = obj
	
	def __getattr__(self, name):
		return getattr(self._obj, name)
	
	def __iter__(self):
		return self
	
	def __next__(self):
		return next(self._obj)

def test_readable_stream_wrapper_read_all(mocker):
	generator_instance = Wrapper(generator())
	close_spy = mocker.spy(generator_instance, "close")
	
	stream = ipfshttpclient.http_common.ReadableStreamWrapper(generator_instance)
	assert stream.read() == b"abcdef()[]{}+++"
	
	close_spy.assert_not_called()
	stream.close()
	close_spy.assert_called_once()

def test_readable_stream_wrapper_read_single_bytes(mocker):
	generator_instance = Wrapper(generator())
	close_spy = mocker.spy(generator_instance, "close")
	
	stream = ipfshttpclient.http_common.ReadableStreamWrapper(generator_instance)
	assert stream.read(1) == b"a"
	assert stream.read(1) == b"b"
	assert stream.read(1) == b"c"
	assert stream.read(1) == b"d"
	assert stream.read(1) == b"e"
	assert stream.read(1) == b"f"
	assert stream.read(1) == b"("
	assert stream.read(1) == b")"
	assert stream.read(1) == b"["
	assert stream.read(1) == b"]"
	assert stream.read(1) == b"{"
	assert stream.read(1) == b"}"
	assert stream.read(1) == b"+"
	assert stream.read(1) == b"+"
	assert stream.read(1) == b"+"
	assert stream.read(1) == b""
	
	close_spy.assert_not_called()
	stream.close()
	close_spy.assert_called_once()

@pytest.mark.parametrize("args,expected", [
	(("/dns/localhost/tcp/5001", "api/v0"),
	 ("http://localhost:5001/api/v0/", socket.AF_UNSPEC, False)),
	
	(("/dns/localhost/tcp/5001/http", "api/v0"),
	 ("http://localhost:5001/api/v0/", socket.AF_UNSPEC, False)),
	
	(("/dns4/localhost/tcp/5001/http", "api/v0"),
	 ("http://localhost:5001/api/v0/", socket.AF_INET, False)),
	
	(("/dns6/localhost/tcp/5001/http", "api/v0/"),
	 ("http://localhost:5001/api/v0/", socket.AF_INET6, False)),
	
	(("/ip4/127.0.0.1/tcp/5001/https", "api/v1/"),
	 ("https://127.0.0.1:5001/api/v1/", socket.AF_INET, True)),
	
	(("/ip6/::1/tcp/5001/https", "api/v1"),
	 ("https://[::1]:5001/api/v1/", socket.AF_INET6, True)),
	
	(("/dns4/ietf.org/tcp/443/https", "/base/"),
	 ("https://ietf.org:443/base/", socket.AF_INET, False)),
])
def test_multiaddr_to_url_data(args, expected):
	assert ipfshttpclient.http_common.multiaddr_to_url_data(*args) == expected

@pytest.mark.parametrize("args", [
	("/dns/localhost", "api/v0"),
	("/ip4/::1/tcp/5001/https", "api/v1/"),
	("/ip4/192.168.250.1/tcp/4001/p2p/QmVgNoP89mzpgEAAqK8owYoDEyB97MkcGvoWZir8otE9Uc", "api/v1/"),
	("/ip4/::1/sctp/5001/https", "api/v1/"),
	("/sctp/5001/http", "api/v0"),
	
	# Should work, but currently doesn't (no proxy support)
	("/dns/localhost/tcp/5001/socks5/dns/ietf.org/tcp/80/http", "/base/"),
	("/dns/proxy-servers.example/tcp/5001/https/dns/ietf.org/tcp/80/http", "/base/"),
	
	# Maybe should also work, but currently doesn't (HTTP/3)
	("/dns/localhost/udp/5001/quic/http", "/base"),
])
def test_multiaddr_to_url_data_invalid(args):
	with pytest.raises(ipfshttpclient.exceptions.AddressError):
		ipfshttpclient.http_common.multiaddr_to_url_data(*args)