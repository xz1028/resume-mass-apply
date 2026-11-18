"""存储仓库层：SQLAlchemy 表定义与各实体 Repository。

领域模型（app/domain）不依赖 SQLAlchemy；本层负责领域对象与 ORM 行的互转。
"""