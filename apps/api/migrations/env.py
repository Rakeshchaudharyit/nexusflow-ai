from alembic import context

from app.core.config import get_settings
from app.db.session import create_database
from app.models import User

target_metadata = User.metadata


def run_migrations_offline():
    context.configure(
        url=get_settings().sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def configure_connection(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    supplied_connection = context.config.attributes.get("connection")
    if supplied_connection is not None:
        configure_connection(supplied_connection)
        return
    engine, _ = create_database(get_settings())
    try:
        with engine.connect() as connection:
            configure_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
