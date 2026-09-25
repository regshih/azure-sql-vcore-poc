IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Products')
               AND name='IX_Products_Tuning_Cover')
    CREATE INDEX IX_Products_Tuning_Cover ON dbo.Products(department,id)
        INCLUDE (sku,name,unit_price_cents,stock_units);
