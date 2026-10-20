# Profile: django

status: verified
namespaces: django
extends: python
docs: https://docs.djangoproject.com/en/<major.minor>/ (the project's Django version), and the installed `django/` source for behaviour the docs leave open

## Detection

All of these:
- `manage.py` that sets `DJANGO_SETTINGS_MODULE`
- `django` in the dependencies (`pyproject.toml`, `requirements*.txt` or the lockfile)
- a settings module with `INSTALLED_APPS`

Record the Django version from the lockfile or `python -c "import django; print(django.get_version())"` in the project's environment. Record the database backend from `DATABASES`, for production and for tests. Several probes depend on the backend.

Note whether tests run with pytest-django (`pytest.ini` or `pyproject.toml` has `DJANGO_SETTINGS_MODULE`) or `manage.py test`. Assertion helpers differ.

## Gates

On top of python's gates.

| Gate | Command | Regression rule |
| --- | --- | --- |
| system checks | `python manage.py check` | any new error or warning |
| deploy checks | `python manage.py check --deploy` with the production settings module, if it loads without secrets | any new warning |
| missing migrations | `python manage.py makemigrations --check --dry-run` | exit code non-zero (model changes without a migration) |
| migration plan | `python manage.py migrate --plan` on the test database | the plan includes the ticket's new migrations, in the expected order |
| migration SQL | `python manage.py sqlmigrate <app> <migration>` for each new migration | the migration-safety rules below |
| migration lint | `python manage.py lintmigrations` (django-migration-linter), only if installed | new findings |

## Migration-safety rules

Review checks; also the basis for the migration-safety probe. Each is about a rolling or two-step deploy, where old code runs against the new schema for a while.

- **Adding a NOT NULL column to an existing table.** It needs a default the database applies (`db_default`, Django 5.0+), or a nullable column, a backfill and a later constraint. A Python-side `default` alone doesn't help old code inserting rows.
- **Removing or renaming a column old code still reads.** It needs two deploys: stop reading, then drop. `RenameField` is a drop and add from old code's point of view.
- **`RunPython` without `reverse_code`.** The migration can't be rolled back. Use `migrations.RunPython.noop` if the reverse really is nothing.
- **Index creation on a large PostgreSQL table.** Use `AddIndexConcurrently` from `django.contrib.postgres.operations`, in a migration with `atomic = False`.
- **`AlterField` that changes type or shrinks length.** Check whether it rewrites or locks the table on this backend (`sqlmigrate`).
- **Data migrations.** They import models with `apps.get_model`, never directly.

## Probes (execution-graded)

| Type | User does | Grading command | Pass |
| --- | --- | --- | --- |
| assert-num-queries | Predicts the number of queries for a request or queryset path in their code, then writes the assertion: `with self.assertNumQueries(n):` in a `TestCase`, or the `django_assert_num_queries(n)` fixture with pytest-django | run that test | prediction equals the observed count, and the test passes |
| explain-plan | Predicts the plan shape for a queryset from their code: joins and their type, subqueries, whether an index on a given column is usable | a scratch test printing `qs.explain()` on the production backend. On PostgreSQL with test-sized data, grade index usability with `SET enable_seqscan = off` in the test. On SQLite, only joins and subqueries are gradable. | the predicted elements appear in the plan |
| migration-safety | For a migration on their branch (or one you mutated from it): predicts the SQL's effect (rewrite, lock, constraint), whether it reverses, and whether the previous release's code keeps working | `sqlmigrate` output; `migrate <app> <previous>` then forward again on the test database; the previous release's tests against the new schema, in a worktree at the last release tag | all three predictions match |
| on-commit | Predicts when a side effect (task enqueue, email, signal handler) runs relative to the transaction, including on rollback | a test using `self.captureOnCommitCallbacks(execute=True)` or the `django_capture_on_commit_callbacks` fixture | predicted callbacks and ordering match |
| predict-then-run, kill-this-mutant | As in python, on views, forms, serializers, managers and signals | as in python | as in python |

Concepts these grade well:
- QuerySet laziness and evaluation
- `select_related` versus `prefetch_related`, N+1
- `annotate` and `aggregate`
- `F` and `Q` expressions
- `update()` and `bulk_*` skipping `save()` and signals
- transactions, `atomic` and `on_commit`
- `select_for_update`
- signals ordering
- model validation versus database constraints
- migrations and two-step deploys
- middleware order, settings split, time zones (`USE_TZ`)

## Logging fields

Beyond the core five:
- `view` (`request.resolver_match.view_name`)
- `route` (`request.resolver_match.route`)
- `db_queries` and `db_ms`, counted with `connection.execute_wrapper()` in a middleware. `connection.queries` is only populated with `DEBUG=True`.
- `cache_hits`, if the app caches

No user, session or tenant identifiers in clear.

## Review checks

- Queries inside loops over querysets (N+1). Prove it with an assertNumQueries test, not by reading.
- Business logic in views or signals, where a service function or model method would be testable alone.
- `save()` overrides or signals assumed to run on `update()` or `bulk_create()`.
- Writes across several models without `transaction.atomic`. Side effects inside the transaction that should be in `on_commit`.
- `get()` without handling `DoesNotExist` or `MultipleObjectsReturned` where input decides.
- Permission checks only in templates or the frontend.
- Raw SQL or `extra()` where the ORM expresses it. Any string-built SQL.
