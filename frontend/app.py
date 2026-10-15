from flask import Flask, jsonify, render_template, request

import config
from services import backend_client

app = Flask(__name__, static_folder="templates/static", static_url_path="/static")
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = (config.MAX_UPLOAD_MB + 1) * 1024 * 1024

PAGES = [
    ("/", "welcome.html", True),
    ("/dashboard", "dashboard.html", False),
    ("/library", "library.html", False),
    ("/tutor", "tutor.html", False),
    ("/quizzes", "quizzes.html", False),
    ("/quiz-results", "quiz_results.html", False),
    ("/progress", "progress.html", False),
    ("/planner", "planner.html", False),
    ("/video-learning", "video_learning.html", False),
    ("/wellness", "wellness.html", False),
    ("/settings", "settings.html", False),
]


def _make_view(template, public):
    def view():
        return render_template(template, public=public)
    return view


for i, (path, template, public) in enumerate(PAGES):
    app.add_url_rule(path, endpoint=f"page{i}", view_func=_make_view(template, public))


@app.route("/api/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def proxy(path):
    return backend_client.forward(request, path)


def _api_error(status, code, message):
    return jsonify({"error": {"code": code, "message": message}}), status


@app.errorhandler(404)
def not_found(_):
    if request.path.startswith("/api/"):
        return _api_error(404, "not_found", "Not found.")
    return render_template("welcome.html", public=True), 404


@app.errorhandler(413)
def too_large(_):
    return _api_error(413, "payload_too_large", f"File is larger than {config.MAX_UPLOAD_MB} MB.")


@app.errorhandler(500)
def server_error(_):
    if request.path.startswith("/api/"):
        return _api_error(500, "internal_error", "An unexpected error occurred.")
    return "Something went wrong. Please go back and try again.", 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.PORT, debug=False)