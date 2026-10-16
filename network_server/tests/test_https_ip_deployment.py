import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'cloud' / 'https_ip'
spec = importlib.util.spec_from_file_location('ip_https_install', SOURCE / 'install_https_ip.py')
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class HttpsIpDeploymentTests(unittest.TestCase):
    def test_certbot_requires_webroot_capable_version(self):
        for version in ('certbot 5.4.0', 'certbot 5.4.1', 'certbot 6.0.0'):
            install.certbot_version(version)
        for version in ('certbot 0.40.0', 'certbot 5.3.9', 'unknown'):
            with self.assertRaises(RuntimeError):
                install.certbot_version(version)

    def test_ip_check_rejects_openssl_zero_exit_mismatch(self):
        install.certificate_ip('IP 118.25.40.152 does match certificate\n')
        for output in ('IP 118.25.40.152 does NOT match certificate',
                       'IP 127.0.0.1 does match certificate', ''):
            with self.assertRaises(RuntimeError):
                install.certificate_ip(output)

    def test_no_activation_without_provider_confirmation(self):
        with patch.object(install, 'run') as run:
            with self.assertRaises(RuntimeError):
                install.activate(False)
            run.assert_not_called()

    def test_existing_nginx_is_not_modified(self):
        with patch.object(install.shutil, 'which', return_value='/usr/sbin/nginx'), \
                patch.object(install, 'run') as run:
            with self.assertRaises(RuntimeError):
                install.prepare()
            run.assert_not_called()

    def test_acme_http_does_not_expose_application(self):
        config = install.asset('nginx-http.conf').decode()
        self.assertIn('location / { return 404; }', config)
        self.assertIn('limit_except GET { deny all; }', config)
        self.assertNotIn('proxy_pass', config)
        self.assertNotIn('listen 443', config)

    def test_public_proxy_read_only_and_tls_only(self):
        config = install.asset('nginx-https.conf').decode()
        http, https = config.split('listen 443 ssl default_server;', 1)
        self.assertNotIn('proxy_pass', http)
        self.assertIn('limit_except GET { deny all; }', https)
        self.assertIn('proxy_pass http://127.0.0.1:18088;', https)
        self.assertIn('proxy_set_header Authorization $http_authorization;', https)
        self.assertIn('ssl_protocols TLSv1.2 TLSv1.3;', https)
        self.assertIn('access_log off;', https)
        self.assertIn('rate=10r/s', config)
        self.assertNotIn('18089', config)

    def test_six_hour_timer_and_hook(self):
        timer = install.asset('tightening-ip-cert-renew.timer').decode()
        hook = install.asset('reload-nginx.sh').decode()
        self.assertIn('00,06,12,18:00:00', timer)
        self.assertIn('Persistent=true', timer)
        self.assertLess(hook.index('nginx -t'), hook.index('reload nginx.service'))

    def test_asset_allowlist(self):
        with self.assertRaises(RuntimeError):
            install.asset('../../etc/shadow')


if __name__ == '__main__':
    unittest.main()
