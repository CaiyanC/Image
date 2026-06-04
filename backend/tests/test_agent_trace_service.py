import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.agent_trace import AgentTrace
from app.services import agent_trace_service


class AgentTraceServiceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[AgentTrace.__table__])
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()

    def test_create_and_complete_trace_records_full_pipeline(self):
        trace = agent_trace_service.create_trace(
            self.db,
            user_id="user-1",
            conversation_id="conversation-1",
            sku="CS-G25",
            question="把 CS-G25 的材质改成 304不锈钢",
        )

        agent_trace_service.complete_trace(
            self.db,
            trace.id,
            intent="update_field",
            parser_output={"sku": "CS-G25", "field_path": "specs.body_material"},
            actions=[{"id": "action-1", "status": "pending"}],
            results=[],
            sources=[{"type": "agent_action"}],
            final_answer="已生成 1 条待确认修改动作。",
            status="success",
        )

        refreshed = self.db.query(AgentTrace).filter(AgentTrace.id == trace.id).first()
        data = agent_trace_service.serialize_trace(refreshed)
        self.assertEqual(data["user_input"]["question"], "把 CS-G25 的材质改成 304不锈钢")
        self.assertEqual(data["intent"], "update_field")
        self.assertEqual(data["parser_output"]["field_path"], "specs.body_material")
        self.assertEqual(data["actions"][0]["id"], "action-1")
        self.assertEqual(data["final_output"]["answer"], "已生成 1 条待确认修改动作。")


if __name__ == "__main__":
    unittest.main()
