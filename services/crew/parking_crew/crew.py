"""
Crew wiring — connects config/agents.yaml, config/tasks.yaml, and tools.py.

Run (after pip install -e services/crew and setting .env credentials):

  from parking_crew.crew import ParkingAuditCrew
  result = ParkingAuditCrew().crew().kickoff(inputs={
      "county_fips": "24510",
      "region_name": "Baltimore City MD",
      "lookback_hours": 168,
      "qualified_score_threshold": 70,
  })
"""

from __future__ import annotations

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task

from parking_crew.env import crew_root
from parking_crew.tools import (
    FINOPS_COMPTROLLER_TOOLS,
    REVENUE_ACTUARY_TOOLS,
    ZONING_ANALYST_TOOLS,
)

_CONFIG_DIR = crew_root() / "config"


@CrewBase
class ParkingAuditCrew:
    """Zoning integrity -> revenue stress-test -> FinOps ROI audit."""

    agents_config = str(_CONFIG_DIR / "agents.yaml")
    tasks_config = str(_CONFIG_DIR / "tasks.yaml")

    @agent
    def zoning_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["zoning_analyst"],  # type: ignore[index]
            tools=ZONING_ANALYST_TOOLS,
            verbose=True,
        )

    @agent
    def revenue_actuary(self) -> Agent:
        return Agent(
            config=self.agents_config["revenue_actuary"],  # type: ignore[index]
            tools=REVENUE_ACTUARY_TOOLS,
            verbose=True,
        )

    @agent
    def finops_comptroller(self) -> Agent:
        return Agent(
            config=self.agents_config["finops_comptroller"],  # type: ignore[index]
            tools=FINOPS_COMPTROLLER_TOOLS,
            verbose=True,
        )

    @task
    def zoning_verification_task(self) -> Task:
        return Task(config=self.tasks_config["zoning_verification_task"])  # type: ignore[index]

    @task
    def financial_stress_test_task(self) -> Task:
        return Task(config=self.tasks_config["financial_stress_test_task"])  # type: ignore[index]

    @task
    def finops_roi_audit_task(self) -> Task:
        return Task(config=self.tasks_config["finops_roi_audit_task"])  # type: ignore[index]

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
