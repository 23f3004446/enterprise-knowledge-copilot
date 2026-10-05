from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import User, UserRole


def seed_demo_users(db: Session) -> None:
    if settings.app_env.lower() == "development":
        demo_users = [
            {
                "email": "employee@example.com",
                "username": "employee",
                "password": "demo_employee_password",
                "role": UserRole.EMPLOYEE.value,
            },
            {
                "email": "manager@example.com",
                "username": "manager",
                "password": "demo_manager_password",
                "role": UserRole.MANAGER.value,
            },
            {
                "email": "admin@example.com",
                "username": "admin",
                "password": "demo_admin_password",
                "role": UserRole.ADMIN.value,
            },
        ]
    else:
        production_users = [
            ("employee@example.com", "employee", settings.initial_employee_password, UserRole.EMPLOYEE.value),
            ("manager@example.com", "manager", settings.initial_manager_password, UserRole.MANAGER.value),
            ("admin@example.com", "admin", settings.initial_admin_password, UserRole.ADMIN.value),
        ]
        demo_users = [
            {"email": email, "username": username, "password": password, "role": role}
            for email, username, password, role in production_users
            if password
        ]

    for user_data in demo_users:
        existing = db.query(User).filter(User.email == user_data["email"]).first()
        if existing is None:
            db.add(
                User(
                    email=user_data["email"],
                    username=user_data["username"],
                    hashed_password=hash_password(user_data["password"]),
                    role=user_data["role"],
                )
            )

    db.commit()
