{{ config(tags=['week05']) }}

select *
from {{ ref('support_kpi_mart') }}
where metric_name in (
    'ticket_count',
    'open_ticket_count',
    'p1_ticket_count',
    'sla_breach_count',
    'escalation_count',
    'avg_backlog_age_days',
    'avg_first_response_minutes',
    'avg_handle_time_minutes',
    'first_resolution_count',
    'resolved_ticket_count'
)
and metric_value < 0
