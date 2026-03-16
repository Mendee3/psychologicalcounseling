from pathlib import Path
import sys

BASE_DIR = Path(__file__).resolve().parent
venv_lib = BASE_DIR / ".venv" / "lib"
for candidate in sorted(venv_lib.glob("python*/site-packages")):
    sys.path.insert(0, str(candidate))

from app import create_app, db
from app.models import AdminUser

app = create_app()

with app.app_context():
    username = input("Admin username: ").strip()
    password = input("Admin password: ").strip()
    user = AdminUser.query.filter_by(username=username).first()
    if not user:
        user = AdminUser(username=username)
        db.session.add(user)
    user.set_password(password)
    user.active = True
    db.session.commit()
    print(f"Admin user '{username}' is ready.")
