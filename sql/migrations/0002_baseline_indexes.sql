CREATE INDEX IX_WorkItems_Status_Id ON dbo.WorkItems(status,id)
    INCLUDE (title,created_at,total_cents);
CREATE INDEX IX_WorkItemLines_Product_WorkItem ON dbo.WorkItemLines(product_id,work_item_id)
    INCLUDE (quantity,unit_price_cents);
CREATE INDEX IX_Activity_WorkItem ON dbo.Activity(work_item_id,id)
    INCLUDE (kind,occurred_at);
CREATE INDEX IX_Products_Department_Id ON dbo.Products(department,id);
