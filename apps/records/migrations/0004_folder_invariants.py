"""Hard DB invariants for folder sharing (ADR-002): the unit boundary must hold even if
application-level validation is bypassed."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION pocketops_folder_unit_consistent() RETURNS trigger AS $$
DECLARE dept_unit uuid;
BEGIN
    SELECT unit_id INTO dept_unit FROM organization_department WHERE id = NEW.owner_department_id;
    IF dept_unit IS DISTINCT FROM NEW.unit_id THEN
        RAISE EXCEPTION 'folder owner_department must belong to folder.unit'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workfolder_unit_consistent
    BEFORE INSERT OR UPDATE ON organization_workfolder
    FOR EACH ROW EXECUTE FUNCTION pocketops_folder_unit_consistent();

CREATE OR REPLACE FUNCTION pocketops_foldergrant_same_unit() RETURNS trigger AS $$
DECLARE f_unit uuid; u_unit uuid;
BEGIN
    SELECT unit_id INTO f_unit FROM organization_workfolder WHERE id = NEW.folder_id;
    SELECT unit_id INTO u_unit FROM accounts_user WHERE id = NEW.user_id;
    IF f_unit IS DISTINCT FROM u_unit THEN
        RAISE EXCEPTION 'folder grant user must belong to folder.unit'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER foldergrant_same_unit
    BEFORE INSERT OR UPDATE ON organization_foldergrant
    FOR EACH ROW EXECUTE FUNCTION pocketops_foldergrant_same_unit();

CREATE OR REPLACE FUNCTION pocketops_recordshare_same_unit() RETURNS trigger AS $$
DECLARE r_unit uuid; u_unit uuid;
BEGIN
    SELECT unit_id INTO r_unit FROM records_workrecord WHERE id = NEW.record_id;
    SELECT unit_id INTO u_unit FROM accounts_user WHERE id = NEW.user_id;
    IF r_unit IS DISTINCT FROM u_unit THEN
        RAISE EXCEPTION 'record share user must belong to record.unit'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER recordshare_same_unit
    BEFORE INSERT OR UPDATE ON records_recordshare
    FOR EACH ROW EXECUTE FUNCTION pocketops_recordshare_same_unit();

CREATE OR REPLACE FUNCTION pocketops_record_folder_consistent() RETURNS trigger AS $$
DECLARE f_unit uuid; f_dept uuid;
BEGIN
    IF NEW.folder_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT unit_id, owner_department_id INTO f_unit, f_dept
        FROM organization_workfolder WHERE id = NEW.folder_id;
    IF f_unit IS DISTINCT FROM NEW.unit_id OR f_dept IS DISTINCT FROM NEW.owner_department_id THEN
        RAISE EXCEPTION 'record folder must share unit and owner_department with the record'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER workrecord_folder_consistent
    BEFORE INSERT OR UPDATE ON records_workrecord
    FOR EACH ROW EXECUTE FUNCTION pocketops_record_folder_consistent();
"""

REVERSE = """
DROP TRIGGER IF EXISTS workfolder_unit_consistent ON organization_workfolder;
DROP TRIGGER IF EXISTS foldergrant_same_unit ON organization_foldergrant;
DROP TRIGGER IF EXISTS recordshare_same_unit ON records_recordshare;
DROP TRIGGER IF EXISTS workrecord_folder_consistent ON records_workrecord;
DROP FUNCTION IF EXISTS pocketops_folder_unit_consistent();
DROP FUNCTION IF EXISTS pocketops_foldergrant_same_unit();
DROP FUNCTION IF EXISTS pocketops_recordshare_same_unit();
DROP FUNCTION IF EXISTS pocketops_record_folder_consistent();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("records", "0003_workrecord_folder_recordshare"),
        ("organization", "0002_workfolder_foldergrant_and_more"),
    ]
    operations = [migrations.RunSQL(SQL, REVERSE)]
