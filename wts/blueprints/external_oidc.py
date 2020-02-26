import flask
import time
from werkzeug.contrib.cache import SimpleCache

from authutils.user import current_user

from ..auth import login_required
from ..models import db, RefreshToken
from ..utils import get_config_var, get_oauth_client


blueprint = flask.Blueprint("external_oidc", __name__)

blueprint.route("")

cache = SimpleCache()


@blueprint.route("/", methods=["GET"])
def get_external_oidc():
    # we use the "providers" field and make "urls" a list to match the format
    # of the Fence "/login" endpoint, and so that we can implement a more
    # complex "login options" logic in the future (automatically get the
    # available login options for each IDP, which could include dropdowns).

    global cache
    if not cache.has("external_oidc"):
        data = {
            "providers": [
                {
                    # name to display on the login button
                    "name": idp_conf["name"],
                    # unique ID of the configured identity provider
                    "idp": idp,
                    # hostname URL - gen3fuse uses it to get the manifests
                    "base_url": oidc_conf["base_url"],
                    # authorization URL to use for logging in
                    "urls": [
                        {
                            "name": idp_conf["name"],
                            "url": generate_authorization_url(idp),
                        }
                    ],
                }
                for oidc_conf in get_config_var("EXTERNAL_OIDC", [])
                for idp, idp_conf in oidc_conf.get("login_options", {}).items()
            ]
        }
        cache.add("external_oidc", data)

    # get the username of the current logged in user
    client, _ = get_oauth_client(idp="default")
    flask.current_app.config["OIDC_ISSUER"] = client.api_base_url.strip("/")
    username = None
    try:
        user = current_user
        username = user.username
    except:
        flask.current_app.logger.info(
            "no logged in user: will return is_connected=False for all IDPs"
        )

    data = cache.get("external_oidc")
    for p in data["providers"]:
        # whether the current user is logged in with this IDP
        p["refresh_token_expiration"] = get_refresh_token_expiration(username, p["idp"])

    return flask.jsonify(data), 200


def generate_authorization_url(idp):
    """
    Args:
        idp (string)

    Returns:
        str: authorization URL to go through the OIDC flow and get a
            refresh token for this IDP
    """
    wts_base_url = get_config_var("WTS_BASE_URL")
    authorization_url = wts_base_url + "oauth2/authorization_url?idp=" + idp
    return authorization_url


def get_refresh_token_expiration(username, idp):
    now = int(time.time())
    refresh_token = (
        db.session.query(RefreshToken)
        .filter_by(username=username)
        .filter_by(idp=idp)
        .order_by(RefreshToken.expires.desc())
        .first()
    )
    if not refresh_token or refresh_token.expires <= now:
        return None
    return refresh_token.expires
