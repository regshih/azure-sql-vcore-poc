IF EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.Products')
           AND name='IX_Products_Tuning_Cover')
    DROP INDEX IX_Products_Tuning_Cover ON dbo.Products;
