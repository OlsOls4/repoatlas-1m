import arrow

arw = arrow.utcnow()
earlier = arw.dehumanize(timestring="2 days ago")  # DOC-LITERAL
print("DOCS_OK")
