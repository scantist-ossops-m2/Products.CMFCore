##############################################################################
#
# Copyright (c) 2001 Zope Foundation and Contributors.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""CookieCrumbler tests.

$Id$
"""

import unittest
import Testing

from zope.component import eventtesting
from zope.interface.verify import verifyClass
from zope.testing.cleanup import cleanUp

def makerequest(root, stdout, stdin=None):
    # Customized version of Testing.makerequest.makerequest()
    from cStringIO import StringIO
    from ZPublisher.HTTPRequest import HTTPRequest
    from ZPublisher.HTTPResponse import HTTPResponse

    resp = HTTPResponse(stdout=stdout)
    environ = {}
    environ['SERVER_NAME'] = 'example.com'
    environ['SERVER_PORT'] = '80'
    environ['REQUEST_METHOD'] = 'GET'
    if stdin is None:
        stdin = StringIO('')  # Empty input
    req = HTTPRequest(stdin, environ, resp)
    req['PARENTS'] = [root]
    return req


class CookieCrumblerTests(unittest.TestCase):

    def _getTargetClass(self):
        from Products.CMFCore.CookieCrumbler  import CookieCrumbler
        return CookieCrumbler

    def _makeOne(self, *args, **kw):
        return self._getTargetClass()(*args, **kw)

    def setUp(self):
        from zope.component import provideHandler
        from zope.component.interfaces import IObjectEvent
        from Products.CMFCore.interfaces import ICookieCrumbler
        from Products.CMFCore.CookieCrumbler import handleCookieCrumblerEvent

        self._finally = None

        eventtesting.setUp()
        provideHandler(handleCookieCrumblerEvent,
                       adapts=(ICookieCrumbler, IObjectEvent))

    def tearDown(self):
        from AccessControl.SecurityManagement import noSecurityManager

        if self._finally is not None:
            self._finally()

        noSecurityManager()
        cleanUp()

    def _makeSite(self):
        import base64
        from cStringIO import StringIO
        import urllib

        from AccessControl.User import UserFolder
        from OFS.Folder import Folder
        from OFS.DTMLMethod import DTMLMethod

        root = Folder()
        root.isTopLevelPrincipiaApplicationObject = 1  # User folder needs this
        root.getPhysicalPath = lambda: ()  # hack
        root._View_Permission = ('Anonymous',)

        users = UserFolder()
        users._setId('acl_users')
        users._doAddUser('abraham', 'pass-w', ('Patriarch',), ())
        users._doAddUser('isaac', 'pass-w', ('Son',), ())
        root._setObject(users.id, users)

        cc = self._makeOne()
        root._setObject(cc.id, cc)

        index = DTMLMethod()
        index.munge('This is the default view')
        index._setId('index_html')
        root._setObject(index.getId(), index)

        login = DTMLMethod()
        login.munge('Please log in first.')
        login._setId('login_form')
        root._setObject(login.getId(), login)

        protected = DTMLMethod()
        protected._View_Permission = ('Manager',)
        protected.munge('This is the protected view')
        protected._setId('protected')
        root._setObject(protected.getId(), protected)

        req = makerequest(root, StringIO())
        self._finally = req.close

        credentials = urllib.quote(
            base64.encodestring('abraham:pass-w').rstrip())

        return root, cc, req, credentials

    def test_interfaces(self):
        from Products.CMFCore.interfaces import ICookieCrumbler

        verifyClass(ICookieCrumbler, self._getTargetClass())

    def testNoCookies(self):
        # verify the cookie crumbler doesn't break when no cookies are given
        root, cc, req, credentials = self._makeSite()
        req.traverse('/')
        self.assertEqual(req['AUTHENTICATED_USER'].getUserName(),
                         'Anonymous User')

    def testCookieLogin(self):
        # verify the user and auth cookie get set
        root, cc, req, credentials = self._makeSite()

        req.cookies['__ac_name'] = 'abraham'
        req.cookies['__ac_password'] = 'pass-w'
        req.traverse('/')

        self.failUnless(req.has_key('AUTHENTICATED_USER'))
        self.assertEqual(req['AUTHENTICATED_USER'].getUserName(),
                         'abraham')
        resp = req.response
        self.failUnless(resp.cookies.has_key('__ac'))
        self.assertEqual(resp.cookies['__ac']['value'],
                         credentials)
        self.assertEqual(resp.cookies['__ac']['path'], '/')

    def testCookieResume(self):
        # verify the cookie crumbler continues the session
        root, cc, req, credentials = self._makeSite()
        req.cookies['__ac'] = credentials
        req.traverse('/')
        self.failUnless(req.has_key('AUTHENTICATED_USER'))
        self.assertEqual(req['AUTHENTICATED_USER'].getUserName(),
                         'abraham')

    def testPasswordShredding(self):
        # verify the password is shredded before the app gets the request
        root, cc, req, credentials = self._makeSite()
        req.cookies['__ac_name'] = 'abraham'
        req.cookies['__ac_password'] = 'pass-w'
        self.failUnless(req.has_key('__ac_password'))
        req.traverse('/')
        self.failIf( req.has_key('__ac_password'))
        self.failIf( req.has_key('__ac'))

    def testCredentialsNotRevealed(self):
        # verify the credentials are shredded before the app gets the request
        root, cc, req, credentials = self._makeSite()
        req.cookies['__ac'] = credentials
        self.failUnless(req.has_key('__ac'))
        req.traverse('/')
        self.failIf( req.has_key('__ac'))

    def testCacheHeaderAnonymous(self):
        # Should not set cache-control
        root, cc, req, credentials = self._makeSite()
        req.traverse('/')
        self.assertEqual(
            req.response.headers.get('cache-control', ''), '')

    def testCacheHeaderLoggingIn(self):
        # Should set cache-control
        root, cc, req, credentials = self._makeSite()
        req.cookies['__ac_name'] = 'abraham'
        req.cookies['__ac_password'] = 'pass-w'
        req.traverse('/')
        self.assertEqual(
            req.response.headers.get('cache-control', ''), 'private')

    def testCacheHeaderAuthenticated(self):
        # Should set cache-control
        root, cc, req, credentials = self._makeSite()
        req.cookies['__ac'] = credentials
        req.traverse('/')
        self.assertEqual(
            req.response.headers.get('cache-control', ''), 'private')

    def testCacheHeaderDisabled(self):
        # Should not set cache-control
        root, cc, req, credentials = self._makeSite()
        cc.cache_header_value = ''
        req.cookies['__ac'] = credentials
        req.traverse('/')
        self.assertEqual(
            req.response.headers.get('cache-control', ''), '')

    def testLoginRatherThanResume(self):
        # When the user presents both a session resume and new
        # credentials, choose the new credentials (so that it's
        # possible to log in without logging out)
        root, cc, req, credentials = self._makeSite()
        req.cookies['__ac_name'] = 'isaac'
        req.cookies['__ac_password'] = 'pass-w'
        req.cookies['__ac'] = credentials
        req.traverse('/')

        self.failUnless(req.has_key('AUTHENTICATED_USER'))
        self.assertEqual(req['AUTHENTICATED_USER'].getUserName(),
                         'isaac')

    def test_before_traverse_hooks(self):
        from OFS.Folder import Folder
        container = Folder()
        cc = self._makeOne()

        marker = []
        bt_before = getattr(container, '__before_traverse__', marker)
        self.failUnless(bt_before is marker)

        container._setObject(cc.id, cc)

        bt_added = getattr(container, '__before_traverse__')
        self.assertEqual(len(bt_added.items()), 1)
        k, v = bt_added.items()[0]
        self.failUnless(k[1].startswith(self._getTargetClass().meta_type))
        self.assertEqual(v.name, cc.id)

        container._delObject(cc.id)

        bt_removed = getattr(container, '__before_traverse__')
        self.assertEqual(len(bt_removed.items()), 0)


def test_suite():
    return unittest.TestSuite((
        unittest.makeSuite(CookieCrumblerTests),
        ))

if __name__ == '__main__':
    unittest.main(defaultTest='test_suite')
