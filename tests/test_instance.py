import json
import os

from app.instance import InstanceLock


def test_only_one_instance_holds_the_lock(tmp_path):
    first = InstanceLock(tmp_path)
    assert first.acquire() is None

    second = InstanceLock(tmp_path)
    holder = second.acquire()
    assert holder is not None
    assert holder["pid"] == os.getpid()

    first.release()
    assert second.acquire() is None
    second.release()


def test_a_stale_lock_is_reclaimed(tmp_path):
    path = tmp_path / "instance.lock"
    path.write_text(json.dumps({"pid": 999999, "port": 0}), encoding="utf-8")

    lock = InstanceLock(tmp_path)
    assert lock.acquire() is None
    assert json.loads(path.read_text(encoding="utf-8"))["pid"] == os.getpid()
    lock.release()


def test_the_chosen_port_is_recorded_for_the_next_launch(tmp_path):
    lock = InstanceLock(tmp_path)
    assert lock.acquire() is None
    lock.set_port(8799)

    holder = InstanceLock(tmp_path).holder()
    assert holder is not None and holder["port"] == 8799
    lock.release()
    assert InstanceLock(tmp_path).holder() is None
