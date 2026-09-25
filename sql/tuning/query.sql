-- Parameterized equivalent used by SqlRepository.diagnostic when tuning_mode is query or both.
SELECT TOP (100) id,sku,name,department,unit_price_cents,stock_units
FROM dbo.Products
WHERE department=@department
ORDER BY id;
