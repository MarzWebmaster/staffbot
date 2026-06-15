import app.database
print([x for x in dir(app.database) if not x.startswith("_")])
