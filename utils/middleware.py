from django.conf import settings


class ContentSecurityPolicyMiddleware:
    """
    Adds the Content-Security-Policy header from settings to every response.

    (Django gets this built in with version 6.0; when the portal moves to
    it, replace this class with django.middleware.csp.)
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.policy = '; '.join(
            '%s %s' % (directive, ' '.join(sources))
            for directive, sources in settings.CONTENT_SECURITY_POLICY.items()
        )

    def __call__(self, request):
        response = self.get_response(request)
        if self.policy and 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = self.policy
        return response
