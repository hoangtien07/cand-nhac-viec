from django.db import migrations

SQL = """
CREATE TRIGGER result_reference_immutable
    BEFORE UPDATE OR DELETE ON records_resultreference
    FOR EACH ROW EXECUTE FUNCTION pocketops_reject_mutation();

CREATE OR REPLACE FUNCTION pocketops_record_completion_immutable() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'work records are never hard-deleted' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.status = 'DONE' AND (
        NEW.status IS DISTINCT FROM OLD.status
        OR NEW.completed_at IS DISTINCT FROM OLD.completed_at
        OR NEW.completed_by_id IS DISTINCT FROM OLD.completed_by_id
    ) THEN
        RAISE EXCEPTION 'completion of a DONE record is immutable' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER work_record_completion_immutable
    BEFORE UPDATE OR DELETE ON records_workrecord
    FOR EACH ROW EXECUTE FUNCTION pocketops_record_completion_immutable();
"""

REVERSE = """
DROP TRIGGER IF EXISTS result_reference_immutable ON records_resultreference;
DROP TRIGGER IF EXISTS work_record_completion_immutable ON records_workrecord;
DROP FUNCTION IF EXISTS pocketops_record_completion_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("records", "0001_initial"), ("audit", "0002_append_only_trigger")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
