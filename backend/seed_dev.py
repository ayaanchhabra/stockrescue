"""DEV ONLY: illustrative products so you can test experiments locally. Not real data."""
from sqlalchemy import func, select

from app import models  # noqa: F401
from app.db.session import SessionLocal
from app.models import Product

with SessionLocal() as db:
    # Schema is managed by Alembic; this seed helper must never create or
    # mutate schema implicitly.
    from sqlalchemy import inspect
    from app.db.session import engine
    if "products" not in inspect(engine).get_table_names():
        raise SystemExit("Database schema is missing. Run `alembic upgrade head` from backend/ first.")
    if db.scalar(select(func.count()).select_from(Product)) == 0:
        db.add_all([
            Product(sku="DEV001", product_name="The God of Small Things", creator_or_brand="Arundhati Roy",
                    quantity_in_stock=24, unit_cost=350, selling_price=499, days_in_stock=90),
            Product(sku="DEV002", product_name="Norwegian Wood", creator_or_brand="Haruki Murakami",
                    quantity_in_stock=15, unit_cost=300, selling_price=450),
            Product(sku="DEV003", product_name="Sapiens", creator_or_brand="Yuval Noah Harari",
                    quantity_in_stock=40, unit_cost=400, selling_price=599),
        ])
        db.commit()
    print("products:", db.scalar(select(func.count()).select_from(Product)))