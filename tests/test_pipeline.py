import copy
import json
import tempfile
import unittest
from importlib.resources import files

from artflow.adapter import Adapter
from artflow.pipeline import validate_pipeline_definition


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.asset = Adapter(files("artflow").joinpath("examples/starter/project.json")).resolve("campfire")
        self.pipeline = copy.deepcopy(self.asset["pipeline"])

    def check(self):
        return validate_pipeline_definition(self.pipeline,self.asset["artifacts"],self.asset["executors"])

    def test_valid_pipeline(self):
        self.assertTrue(self.check()["ok"])

    def test_cycles_rejected(self):
        self.pipeline["steps"][0]["depends_on"]=["verify"]
        self.assertFalse(self.check()["ok"])

    def test_unknown_artifact_rejected(self):
        self.pipeline["steps"][0]["inputs"]=["missing"]
        self.assertFalse(self.check()["ok"])

    def test_unknown_executor_rejected(self):
        self.pipeline["steps"][0]["executor"]="missing"
        self.assertFalse(self.check()["ok"])

    def test_unapproved_write_rejected(self):
        self.pipeline["steps"][0]["requires_approval"]=False
        self.assertFalse(self.check()["ok"])

    def test_step_cannot_declare_output_without_write_boundary(self):
        self.pipeline["steps"][0]["writes"]=False
        self.pipeline["steps"][0]["requires_approval"]=False
        self.assertFalse(self.check()["ok"])
        self.assertTrue(any("outputs must set writes" in error["message"] for error in self.check()["errors"]))

    def test_unknown_command_rejected(self):
        self.pipeline["steps"][0]["command"]=["delete","everything"]
        self.assertFalse(self.check()["ok"])

    def test_input_producer_dependency_required(self):
        self.pipeline["steps"][1]["depends_on"]=[]
        self.assertFalse(self.check()["ok"])

    def test_unordered_write_conflict_checks_resolved_paths(self):
        self.asset["artifacts"]["alias"]={**self.asset["artifacts"]["image"]}
        new=copy.deepcopy(self.pipeline["steps"][0])
        new.update(id="other",outputs=["alias"])
        self.pipeline["steps"].append(new)
        self.assertFalse(self.check()["ok"])

    def test_approval_of_new_output_requires_separate_action(self):
        step=self.pipeline["steps"][1]
        step.update(writes=True,requires_approval=True,approval_artifacts=["image"],outputs=["image"],locks=["test"])
        self.assertFalse(self.check()["ok"])

    def test_sequential_overwrite_requires_versioned_output(self):
        new=copy.deepcopy(self.pipeline["steps"][0])
        new.update(id="overwrite", depends_on=["build"])
        self.pipeline["steps"].append(new)
        self.assertFalse(self.check()["ok"])

    def test_publish_references_are_checked(self):
        self.pipeline["actions"]["build"]["publish_artifacts"]=["missing"]
        self.assertFalse(self.check()["ok"])
