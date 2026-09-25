CREATE TABLE dbo.Products (
    id int NOT NULL CONSTRAINT PK_Products PRIMARY KEY,
    sku varchar(32) NOT NULL CONSTRAINT UQ_Products_Sku UNIQUE,
    name nvarchar(120) NOT NULL,
    department varchar(20) NOT NULL,
    unit_price_cents int NOT NULL,
    stock_units int NOT NULL,
    CONSTRAINT CK_Products_Department CHECK (department IN ('operations','engineering','sales')),
    CONSTRAINT CK_Products_Price CHECK (unit_price_cents >= 0),
    CONSTRAINT CK_Products_Stock CHECK (stock_units >= 0)
);
CREATE TABLE dbo.WorkItems (
    id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_WorkItems PRIMARY KEY,
    title nvarchar(120) NOT NULL,
    status varchar(16) NOT NULL,
    created_at datetime2(3) NOT NULL CONSTRAINT DF_WorkItems_Created DEFAULT SYSUTCDATETIME(),
    total_cents bigint NOT NULL,
    CONSTRAINT CK_WorkItems_Status CHECK (status IN ('open','completed')),
    CONSTRAINT CK_WorkItems_Total CHECK (total_cents >= 0)
);
CREATE TABLE dbo.WorkItemLines (
    work_item_id bigint NOT NULL,
    product_id int NOT NULL,
    quantity int NOT NULL,
    unit_price_cents int NOT NULL,
    ordinal int NOT NULL,
    CONSTRAINT PK_WorkItemLines PRIMARY KEY (work_item_id,product_id),
    CONSTRAINT FK_WorkItemLines_WorkItem FOREIGN KEY (work_item_id) REFERENCES dbo.WorkItems(id),
    CONSTRAINT FK_WorkItemLines_Product FOREIGN KEY (product_id) REFERENCES dbo.Products(id),
    CONSTRAINT CK_WorkItemLines_Quantity CHECK (quantity BETWEEN 1 AND 1000),
    CONSTRAINT CK_WorkItemLines_Price CHECK (unit_price_cents >= 0),
    CONSTRAINT CK_WorkItemLines_Ordinal CHECK (ordinal BETWEEN 0 AND 49),
    CONSTRAINT UQ_WorkItemLines_Ordinal UNIQUE (work_item_id,ordinal)
);
CREATE TABLE dbo.Activity (
    id bigint IDENTITY(1,1) NOT NULL CONSTRAINT PK_Activity PRIMARY KEY,
    work_item_id bigint NOT NULL,
    kind varchar(32) NOT NULL CONSTRAINT DF_Activity_Kind DEFAULT 'work_item_created',
    occurred_at datetime2(3) NOT NULL CONSTRAINT DF_Activity_Occurred DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_Activity_WorkItem FOREIGN KEY (work_item_id) REFERENCES dbo.WorkItems(id),
    CONSTRAINT CK_Activity_Kind CHECK (kind='work_item_created')
);
CREATE TABLE dbo.IdempotencyKeys (
    [key] varchar(128) COLLATE Latin1_General_100_BIN2 NOT NULL CONSTRAINT PK_IdempotencyKeys PRIMARY KEY,
    command_hash binary(32) NOT NULL,
    work_item_id bigint NOT NULL,
    created_at datetime2(3) NOT NULL CONSTRAINT DF_Idempotency_Created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_Idempotency_WorkItem FOREIGN KEY (work_item_id) REFERENCES dbo.WorkItems(id)
);
CREATE TABLE dbo.DatasetVersions (
    version varchar(100) NOT NULL CONSTRAINT PK_DatasetVersions PRIMARY KEY,
    generation_seed int NOT NULL,
    product_count int NOT NULL,
    work_item_count int NOT NULL,
    created_at datetime2(3) NOT NULL CONSTRAINT DF_DatasetVersions_Created DEFAULT SYSUTCDATETIME()
);
CREATE TABLE dbo.RuntimeConfiguration (
    [key] varchar(40) NOT NULL CONSTRAINT PK_RuntimeConfiguration PRIMARY KEY,
    value varchar(40) NOT NULL
);
INSERT dbo.RuntimeConfiguration([key],value) VALUES ('tuning_mode','baseline');
