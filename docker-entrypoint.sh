#!/bin/sh
set -e

echo "===> Applying database migrations..."
python manage.py migrate --noinput

DOC_COUNT=$(python manage.py shell -c "from search.models import Document; print(Document.objects.count())" 2>/dev/null | tail -n 1 || echo 0)
if [ "$DOC_COUNT" = "0" ]; then
  echo "===> Empty index detected. Building index from data/corpus/..."
  python manage.py build_index || true
fi

echo "===> Starting Django at 0.0.0.0:8000"
exec python manage.py runserver 0.0.0.0:8000
