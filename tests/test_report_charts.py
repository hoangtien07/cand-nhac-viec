"""Chart.js report aggregates: truthful, scoped, mutually exclusive, table fallback."""

import json
import re

import pytest

from apps.organization import folder_services
from apps.organization.models import FolderRole

from .conftest import make_record
from .test_folder_models import make_folder


def _json_script(body, element_id):
    m = re.search(
        rf'<script[^>]*id="{element_id}"[^>]*type="application/json"[^>]*>(.*?)</script>',
        body,
        re.S,
    )
    assert m, "json_script payload missing"
    return json.loads(m.group(1))


@pytest.mark.django_db
def test_report_page_renders_chart_payload_and_tables(org, client_for):
    make_record(org.mgr1, org.d1, [org.o1], ref="RPT-1")
    res = client_for(org.leader).get("/bao-cao/")
    body = res.content.decode()
    assert res.status_code == 200
    data = _json_script(body, "report-charts-data")
    assert set(data) == {"monthly", "status", "by_folder", "overdue_age"}
    assert len(data["monthly"]["labels"]) == 12
    assert "chart-monthly" in body and "chart.umd.js" in body
    # Accessible fallback tables exist for every chart
    assert body.count("Bảng số liệu") >= 4


@pytest.mark.django_db
def test_status_buckets_are_mutually_exclusive(org, client_for):
    from apps.records import services

    make_record(org.mgr1, org.d1, [org.o1], ref="RPT-A", days=5)
    rec_done = make_record(org.mgr1, org.d1, [org.o1], ref="RPT-B", days=5)
    services.submit_result_reference(org.o1, rec_done.pk, code="KQ-RPT-B")
    make_record(org.mgr1, org.d1, [org.o1], ref="RPT-C", days=-5)  # overdue

    res = client_for(org.leader).get("/bao-cao/")
    data = _json_script(res.content.decode(), "report-charts-data")
    assert sum(data["status"]["counts"]) == res.context["totals"]["total"]
    assert res.context["totals"]["total"] == 3


@pytest.mark.django_db
def test_folder_comparison_scoped_to_unit(org, client_for):
    fa = make_folder(org.ua, org.d1, org.mgr1, name="Nhóm RPT-A")
    fb_b = make_folder(org.ub, org.d3, org.bleader, name="Nhóm RPT-B")
    ra = make_record(org.mgr1, org.d1, [org.o1], ref="RPT-FA")
    ra.folder = fa
    ra.save()
    rb = make_record(org.bleader, org.d3, [org.b1], ref="RPT-FB")
    rb.folder = fb_b
    rb.save()

    res = client_for(org.leader).get("/bao-cao/")
    data = _json_script(res.content.decode(), "report-charts-data")
    assert data["by_folder"]["labels"] == ["Nhóm RPT-A"]
    assert "Nhóm RPT-B" not in res.content.decode()

    res_b = client_for(org.bleader).get("/bao-cao/")
    data_b = _json_script(res_b.content.decode(), "report-charts-data")
    assert data_b["by_folder"]["labels"] == ["Nhóm RPT-B"]


@pytest.mark.django_db
def test_officer_report_scope_unchanged(org, client_for):
    make_record(org.mgr1, org.d1, [org.o1], ref="RPT-O1")
    make_record(org.leader, org.d1, [org.o2], ref="RPT-O2")
    res = client_for(org.o1).get("/bao-cao/")
    data = _json_script(res.content.decode(), "report-charts-data")
    # o1 only participates in RPT-O1; folder grants/shares do not widen report scope
    assert res.context["totals"]["total"] == 1
    assert sum(data["status"]["counts"]) == 1


@pytest.mark.django_db
def test_folder_grant_does_not_widen_report_counts(org, client_for):
    fa = make_folder(org.ua, org.d1, org.mgr1)
    folder_services.grant_folder(org.mgr1, fa.pk, org.o2.pk, FolderRole.VIEWER)
    rec = make_record(org.leader, org.d1, [org.o1], ref="RPT-GR")
    rec.folder = fa
    rec.save()
    res = client_for(org.o2).get("/bao-cao/")
    assert res.context["totals"]["total"] == 0


@pytest.mark.django_db
def test_monthly_counts_created(org, client_for):
    rec = make_record(org.mgr1, org.d1, [org.o1], ref="RPT-M")
    res = client_for(org.leader).get("/bao-cao/")
    data = _json_script(res.content.decode(), "report-charts-data")
    month_key = rec.created_at.strftime("%Y-%m")
    idx = data["monthly"]["labels"].index(month_key)
    assert data["monthly"]["created"][idx] == 1
