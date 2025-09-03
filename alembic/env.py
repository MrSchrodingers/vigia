from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

VERSION_TABLE_NAME = "alembic_version"
VERSION_TABLE_SCHEMA = "public"

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from db.models import Base  # noqa: E402
from vigia.config import settings  # noqa: E402

target_metadata = Base.metadata
config.set_main_option('sqlalchemy.url', settings.DATABASE_URL)

def include_object(object, name, type_, reflected, compare_to):
    # Ignore a tabela de versão para a autogeração
    if type_ == "table" and name == VERSION_TABLE_NAME:
        return False
    return True

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        version_table_schema=VERSION_TABLE_SCHEMA,
        version_table_create=True,     
        include_object=include_object, 
        compare_type=True,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=VERSION_TABLE_SCHEMA,
            version_table_create=True,     
            include_object=include_object, 
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
