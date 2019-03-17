#include "worker.h"

#include <boost/bind.hpp>

#include "ray/raylet/format/node_manager_generated.h"
#include "ray/raylet/raylet.h"

namespace ray {

namespace raylet {

/// A constructor responsible for initializing the state of a worker.
Worker::Worker(pid_t pid, const Language &language,
               std::shared_ptr<LocalClientConnection> connection)
    : pid_(pid),
      language_(language),
      connection_(connection),
      dead_(false),
      blocked_(false) {}

void Worker::MarkDead() { dead_ = true; }

bool Worker::IsDead() const { return dead_; }

void Worker::MarkBlocked() { blocked_ = true; }

void Worker::MarkUnblocked() { blocked_ = false; }

bool Worker::IsBlocked() const { return blocked_; }

pid_t Worker::Pid() const { return pid_; }

Language Worker::GetLanguage() const { return language_; }

// TODO(ujvl) remove this
void Worker::AssignTaskId(const TaskID &task_id) {
  assigned_task_ids_.clear();
  assigned_task_ids_.push_back(task_id);
}

void Worker::AssignTaskIds(const std::vector<TaskID> &task_ids) {
  assigned_task_ids_ = task_ids;
}

// TODO(ujvl) remove this
const TaskID &Worker::GetAssignedTaskId() const {
  RAY_CHECK(assigned_task_ids_.size() == 1);
  return assigned_task_ids_[0];
}

const std::vector<TaskID> &Worker::GetAssignedTaskIds() const {
  return assigned_task_ids_;
}

bool Worker::AddBlockedTaskId(const TaskID &task_id) {
  auto inserted = blocked_task_ids_.insert(task_id);
  return inserted.second;
}

bool Worker::RemoveBlockedTaskId(const TaskID &task_id) {
  auto erased = blocked_task_ids_.erase(task_id);
  return erased == 1;
}

const std::unordered_set<TaskID> &Worker::GetBlockedTaskIds() const {
  return blocked_task_ids_;
}

void Worker::AssignDriverId(const DriverID &driver_id) {
  assigned_driver_id_ = driver_id;
}

const DriverID &Worker::GetAssignedDriverId() const { return assigned_driver_id_; }

void Worker::AssignActorId(const ActorID &actor_id) {
  RAY_CHECK(actor_id_.is_nil())
      << "A worker that is already an actor cannot be assigned an actor ID again.";
  RAY_CHECK(!actor_id.is_nil());
  actor_id_ = actor_id;
}

const ActorID &Worker::GetActorId() const { return actor_id_; }

const std::shared_ptr<LocalClientConnection> Worker::Connection() const {
  return connection_;
}

const ResourceIdSet &Worker::GetLifetimeResourceIds() const {
  return lifetime_resource_ids_;
}

void Worker::ResetLifetimeResourceIds() { lifetime_resource_ids_.Clear(); }

void Worker::SetLifetimeResourceIds(ResourceIdSet &resource_ids) {
  lifetime_resource_ids_ = resource_ids;
}

const ResourceIdSet &Worker::GetTaskResourceIds() const { return task_resource_ids_; }

void Worker::ResetTaskResourceIds() { task_resource_ids_.Clear(); }

void Worker::SetTaskResourceIds(ResourceIdSet &resource_ids) {
  task_resource_ids_ = resource_ids;
}

ResourceIdSet Worker::ReleaseTaskCpuResources() {
  auto cpu_resources = task_resource_ids_.GetCpuResources();
  // The "acquire" terminology is a bit confusing here. The resources are being
  // "acquired" from the task_resource_ids_ object, and so the worker is losing
  // some resources.
  task_resource_ids_.Acquire(cpu_resources.ToResourceSet());
  return cpu_resources;
}

void Worker::AcquireTaskCpuResources(const ResourceIdSet &cpu_resources) {
  // The "release" terminology is a bit confusing here. The resources are being
  // given back to the worker and so "released" by the caller.
  task_resource_ids_.Release(cpu_resources);
}

}  // namespace raylet

}  // end namespace ray
