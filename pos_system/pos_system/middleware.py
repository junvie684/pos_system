from django.utils.cache import add_never_cache_headers


class NoStoreWhenSignedInMiddleware:
    """
    Pages seen while signed in must not be kept by the browser. Without this,
    pressing Back after signing out shows a saved copy of the last screen
    (sales figures, a customer, the cart) to whoever uses the counter next.
    With `Cache-Control: no-store` the browser asks the server again instead,
    and the server, finding no session, sends it to the sign-in page.

    The check runs on the request as it arrived: the sign-out response itself
    is covered too, though its user is already signed out by then.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        signed_in = request.user.is_authenticated
        response = self.get_response(request)
        if signed_in:
            add_never_cache_headers(response)   # no-store, no-cache, must-revalidate, private
        return response
