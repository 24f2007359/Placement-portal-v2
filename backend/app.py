import os

from flask import Flask
from flask_cors import CORS

from config import Config
from models import db
from admin_routes import admin_bp
from company_routes import company_bp
from routes import auth_bp, dashboard_bp

app = Flask(__name__)
app.config.from_object(Config)

os.makedirs(app.instance_path, exist_ok=True)

db.init_app(app)
CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"])

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(company_bp)


@app.route("/api/health")
def health():
    return {"status": "ok", "message": "Placement Portal API"}


if __name__ == "__main__":
    app.run(debug=True, port=5000)
