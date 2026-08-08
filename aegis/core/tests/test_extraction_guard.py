"""Extraction guardrail: aegis.* must not import Beacon apps.

Beacon is the incubator, not the product. The only permitted contact with Beacon
is through runtime seams (e.g. BeaconSessionProvider reading request.user, or the
bootstrap seed reading auth.User via get_user_model) — never a static import of a
Beacon app package.
"""
import ast
import os

from django.test import SimpleTestCase

import aegis

BEACON_APP_PACKAGES = {
    'finance', 'wlj', 'products', 'website', 'admin_console', 'distribution',
}


class ExtractionGuardTests(SimpleTestCase):
    def test_aegis_does_not_import_beacon_apps(self):
        root = os.path.dirname(os.path.abspath(aegis.__file__))
        offenders = []
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if not filename.endswith('.py'):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, encoding='utf-8') as handle:
                    tree = ast.parse(handle.read(), filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.split('.')[0] in BEACON_APP_PACKAGES:
                                offenders.append((path, alias.name))
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        if node.module.split('.')[0] in BEACON_APP_PACKAGES:
                            offenders.append((path, node.module))
        self.assertEqual(
            offenders, [], f'aegis must not import Beacon apps: {offenders}'
        )
