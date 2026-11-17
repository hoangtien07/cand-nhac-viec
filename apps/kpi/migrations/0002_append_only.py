from django.db import migrations

TABLES = [
    ("kpi_kpiscoresnapshot", "kpi_snapshot_append_only"),
    ("kpi_kpiscorecorrection", "kpi_correction_append_only"),
    ("kpi_kpireminderevent", "kpi_reminder_append_only"),
    ("kpi_kpireminderrevocation", "kpi_revocation_append_only"),
]

SQL = (
    """
CREATE OR REPLACE FUNCTION pocketops_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'append-only table %: % rejected', TG_TABLE_NAME, TG_OP USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""
    + "".join(
        f"""
CREATE TRIGGER {trigger}
    BEFORE UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION pocketops_reject_mutation();
"""
        for table, trigger in TABLES
    )
)

REVERSE = "".join(f"DROP TRIGGER IF EXISTS {trigger} ON {table};\n" for table, trigger in TABLES)


class Migration(migrations.Migration):
    dependencies = [("kpi", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
