"""Defines the existing frontend routes so the Pyramid router can pass them along."""
from urlparse import urljoin, urlparse
import urllib

from ..models import Discussion


URL_DISCRIMINANTS = {
    'SOURCE': 'source',
    'NEXT': 'next'
}

SOURCE_DISCRIMINANTS = {
    'NOTIFICATION': 'notification',
    'SHARE': 'share'
}

ATTACHMENT_PURPOSES = {
    'EMBED_ATTACHMENT': 'EMBED_ATTACHMENT'
}


class FrontendUrls(object):
    """The set of FrontendUrls."""
    def __init__(self, discussion):
        assert isinstance(discussion, Discussion)
        self.discussion = discussion

    frontend_discussion_routes = {
        'edition': '/edition',
        'partners': '/partners',
        'settings': '/settings',
        'timeline': '/timeline',
        'about': '/about',
        'admin_discussion_preferences': '/discussion_preferences',
        'notifications': '/notifications',
        'user_notifications': '/user/notifications',
        'profile': '/user/profile',
        'account': '/user/account',
        'user_discussion_preferences': '/user/discussion_preferences',
        'sentrytest': '/sentrytest',
        'groupSpec': '/G/*remainder',
        'purl_posts': '/posts*remainder',
        'purl_idea': '/idea*remainder',
        'purl_user': '/profile*remainder',
        'purl_widget': '/widget*remainder'
    }
    """
    The list of frontend discussion routes.

    Important:  This should match with :js:class:`Router`
    Used by :py:func:`assembl.views.backbone.views.home_view`, these routes
    will all give the same view and further routing will happen
    in the frontend."""

    frontend_admin_routes = {
        'admin_global_preferences': '/global_preferences',
    }
    """
    The list of frontend discussion routes.

    Important:  This should match with :js:class:`Router`
    Used by :py:func:`assembl.views.backbone.views.home_view`, these routes
    will all give the same view and further routing will happen
    in the frontend."""

    @classmethod
    def register_frontend_routes(cls, config):
        from assembl.views.discussion.views import home_view
        for name, route in cls.frontend_discussion_routes.iteritems():
            config.add_route(name, route)
            config.add_view(
                home_view, route_name=name, request_method='GET',
                http_cache=60)

    @classmethod
    def register_frontend_admin_routes(cls, config):
        from assembl.views.admin.views import base_admin_view
        for name, route in cls.frontend_admin_routes.iteritems():
            config.add_route(name, route)
            config.add_view(
                base_admin_view, route_name=name, request_method='GET',
                http_cache=60)

    @classmethod
    def register_legacy_routes(cls, config):
        from assembl.views.discussion.views import home_view
        for name, route in cls.frontend_discussion_routes.iteritems():
            if name.startswith('purl'):
                name = 'legacy_' + name
                config.add_route(name, route)
                config.add_view(
                    home_view, route_name=name, request_method='GET',
                    http_cache=60)

    # used for route 'purl_posts': '/posts*remainder'
    @staticmethod
    def getRequestedPostId(request):
        if 'remainder' in request.matchdict:
            return '/'.join(i for i in request.matchdict['remainder'])
        return None

    # used for route 'purl_idea': '/idea*remainder'
    @staticmethod
    def getRequestedIdeaId(request):
        if 'remainder' in request.matchdict:
            return '/'.join(i for i in request.matchdict['remainder'])
        return None

    def getDiscussionLogoUrl(self):
        return urljoin(
            self.discussion.get_base_url(), '/static/img/assembl.png')

    def get_discussion_url(self, request=None):
        """
        from pyramid.request import Request
        req = Request.blank('/', base_url=self.discussion.get_base_url())
        Celery didn't like this.  To revisit once we have virtual hosts
        return req.route_url('home', discussion_slug=self.discussion.slug)

        Returns the legacy URL route. Currently, /debate/{discussion_slug}
        """

        from assembl.views import create_get_route
        if request is None:
            # Shouldn't do this. Method should only be used in context
            # of a request!
            from pyramid.threadlocal import get_current_request
            request = get_current_request()

        # TODO: If the route for 'home' is EVER changed, this value MUST be
        # synced. KEEP it as 'home' instead of 'new_home', because usage of
        # this method is kept mostly for legacy routes that do not exist in
        # new front-end yet.
        if request is None:
            route = '/debate/' + self.discussion.slug
        else:
            get_route = create_get_route(request, self.discussion)
            route = get_route('home')
        return urljoin(self.discussion.get_base_url(), route)

    # TODO: Decommission all of the route methods below. They are
    # no longer Object Oriented.
    def getUserNotificationSubscriptionsConfigurationUrl(self):
        return self.get_discussion_url() + '/user/notifications'

    def getUserNotificationSubscriptionUnsubscribeUrl(self, subscription):
        """ TODO:  Give an actual subscription URL """
        return self.getUserNotificationSubscriptionsConfigurationUrl()

    def get_relative_post_url(self, post):
        return '/posts/' + urllib.quote(post.uri(), '')

    def get_post_url(self, post):
        return self.get_discussion_url() + self.get_relative_post_url(post)

    def get_relative_idea_url(self, idea):
        return '/idea/' + urllib.quote(idea.original_uri, '')

    def get_idea_url(self, idea):
        return self.get_discussion_url() + self.get_relative_idea_url(idea)

    def get_discussion_edition_url(self):
        return self.get_discussion_url() + '/edition'

    def append_query_string(self, url, **kwargs):
        if not url:
            return ''
        if url[-1] is '/':
            url = url[:-1]
        url_base = url + '?'
        f = lambda k, v: "%s=%s" % (k, v)
        qs = [f(k, v) for k, v in kwargs.iteritems() if k]
        return url_base + ('&'.join(qs)) if kwargs else ''

    def get_agentprofile_avatar_url(self, profile, pixelSize):
        return urljoin(
            self.discussion.get_base_url(), profile.external_avatar_url()+str(pixelSize))
