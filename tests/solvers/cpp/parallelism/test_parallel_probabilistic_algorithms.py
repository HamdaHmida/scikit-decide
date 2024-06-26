# Copyright (c) AIRBUS and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from collections import namedtuple
from enum import Enum
from math import sqrt
from typing import NamedTuple, Optional

from pathos.helpers import mp
from tqdm import tqdm

from skdecide import (
    DiscreteDistribution,
    EnvironmentOutcome,
    GoalMDPDomain,
    Space,
    TransitionOutcome,
    Value,
)
from skdecide.builders.domain import Actions
from skdecide.hub.solver.mcts.mcts import MCTS
from skdecide.hub.space.gym import EnumSpace, ListSpace, MultiDiscreteSpace
from skdecide.utils import load_registered_solver, rollout


class State(NamedTuple):
    x: int
    y: int


class Action(Enum):
    up = 0
    down = 1
    left = 2
    right = 3


class D(GoalMDPDomain, Actions):
    T_state = State  # Type of states
    T_observation = T_state  # Type of observations
    T_event = Action  # Type of events
    T_value = float  # Type of transition values (rewards or costs)
    T_predicate = bool  # Type of logical checks
    T_info = (
        None  # Type of additional information given as part of an environment outcome
    )


class MyDomain(D):
    def __init__(self, num_cols=10, num_rows=10):
        self.num_cols = num_cols
        self.num_rows = num_rows

    def _get_applicable_actions_from(
        self, memory: D.T_memory[D.T_state]
    ) -> D.T_agent[Space[D.T_event]]:
        applicable_actions = []
        if memory.y > 0:
            applicable_actions.append(Action.up)
        if memory.y < self.num_rows - 1:
            applicable_actions.append(Action.down)
        if memory.x > 0:
            applicable_actions.append(Action.left)
        if memory.x < self.num_cols - 1:
            applicable_actions.append(Action.right)
        return ListSpace(applicable_actions)

    def _get_next_state_distribution(
        self,
        memory: D.T_memory[D.T_state],
        action: D.T_agent[D.T_concurrency[D.T_event]],
    ) -> DiscreteDistribution[D.T_state]:

        if action == Action.left:
            next_state_1 = State(max(memory.x - 1, 0), memory.y)
            next_state_2 = State(max(memory.x - 1, 0), max(memory.y - 1, 0))
            next_state_3 = State(
                max(memory.x - 1, 0), min(memory.y + 1, self.num_rows - 1)
            )
        if action == Action.right:
            next_state_1 = State(min(memory.x + 1, self.num_cols - 1), memory.y)
            next_state_2 = State(
                min(memory.x + 1, self.num_cols - 1),
                min(memory.y + 1, self.num_rows - 1),
            )
            next_state_3 = State(
                min(memory.x + 1, self.num_cols - 1), max(memory.y - 1, 0)
            )
        if action == Action.up:
            next_state_1 = State(memory.x, max(memory.y - 1, 0))
            next_state_2 = State(max(memory.x - 1, 0), max(memory.y - 1, 0))
            next_state_3 = State(
                min(memory.x + 1, self.num_cols - 1), max(memory.y - 1, 0)
            )
        if action == Action.down:
            next_state_1 = State(memory.x, min(memory.y + 1, self.num_rows - 1))
            next_state_2 = State(
                min(memory.x + 1, self.num_cols - 1),
                min(memory.y + 1, self.num_rows - 1),
            )
            next_state_3 = State(
                max(memory.x - 1, 0), min(memory.y + 1, self.num_rows - 1)
            )

        return DiscreteDistribution(
            [
                (memory, 0.2),
                (next_state_1, 0.4),
                (next_state_2, 0.2),
                (next_state_3, 0.2),
            ]
        )

    def _get_transition_value(
        self,
        memory: D.T_memory[D.T_state],
        action: D.T_agent[D.T_concurrency[D.T_event]],
        next_state: Optional[D.T_state] = None,
    ) -> D.T_agent[Value[D.T_value]]:
        # every move costs 1
        return Value(cost=abs(next_state.x - memory.x) + abs(next_state.y - memory.y))

    def _is_terminal(self, state: D.T_state) -> D.T_agent[D.T_predicate]:
        return self._is_goal(state)

    def _get_action_space_(self) -> D.T_agent[Space[D.T_event]]:
        return EnumSpace(Action)

    def _get_goals_(self) -> D.T_agent[Space[D.T_observation]]:
        return ListSpace([State(x=self.num_cols - 1, y=self.num_rows - 1)])

    def _get_initial_state_(self) -> D.T_state:
        return State(x=0, y=0)

    def _get_observation_space_(self) -> D.T_agent[Space[D.T_observation]]:
        return MultiDiscreteSpace([self.num_cols, self.num_rows])


class GridShmProxy:

    _register_ = [
        (State, 2),
        (Action, 1),
        (EnumSpace, 1),
        (ListSpace, 1),
        (DiscreteDistribution, 1),
        (Value, 1),
        (EnvironmentOutcome, 1),
        (TransitionOutcome, 1),
        (bool, 1),
        (float, 1),
        (int, 2),
    ]

    def __init__(self):
        self._proxies_ = {
            State: GridShmProxy.StateProxy,
            Action: GridShmProxy.ActionProxy,
            EnumSpace: GridShmProxy.EnumSpaceProxy,
            ListSpace: GridShmProxy.ListSpaceProxy,
            DiscreteDistribution: GridShmProxy.DiscreteDistributionProxy,
            Value: GridShmProxy.ValueProxy,
            EnvironmentOutcome: GridShmProxy.EnvironmentOutcomeProxy,
            TransitionOutcome: GridShmProxy.TransitionOutcomeProxy,
            bool: GridShmProxy.BoolProxy,
            float: GridShmProxy.FloatProxy,
            int: GridShmProxy.IntProxy,
        }

    def copy(self):
        p = GridShmProxy()
        p._proxies_ = dict(self._proxies_)
        return p

    def register(self):
        return GridShmProxy._register_

    def initialize(self, t):
        return self._proxies_[t].initialize()

    def encode(self, value, shm_value):
        self._proxies_[type(value)].encode(value, shm_value)

    def decode(self, t, shm_value):
        return self._proxies_[t].decode(shm_value)

    class StateProxy:
        @staticmethod
        def initialize():
            return mp.Array("d", [0, 0], lock=True)

        @staticmethod
        def encode(state, shm_state):
            shm_state[0] = state.x
            shm_state[1] = state.y

        @staticmethod
        def decode(shm_state):
            return State(int(shm_state[0]), int(shm_state[1]))

    class ActionProxy:
        @staticmethod
        def initialize():
            return mp.Value("I", 0, lock=True)

        @staticmethod
        def encode(action, shm_action):
            shm_action.value = action.value

        @staticmethod
        def decode(shm_action):
            return Action(shm_action.value)

    class EnumSpaceProxy:  # Always used with Action as enum class
        @staticmethod
        def initialize():
            return mp.Array("c", b"")

        @staticmethod
        def encode(val, shm_val):
            pass

        @staticmethod
        def decode(val):
            return EnumSpace(Action)

    class ListSpaceProxy:  # Always used with Action as enum class
        @staticmethod
        def initialize():
            return mp.Array("b", [False, False, False, False], lock=True)

        @staticmethod
        def encode(val, shm_val):
            for i in range(4):
                shm_val[i] = False
            for a in val.get_elements():
                if a is Action.up:
                    shm_val[0] = True
                elif a is Action.down:
                    shm_val[1] = True
                elif a is Action.left:
                    shm_val[2] = True
                elif a is Action.right:
                    shm_val[3] = True

        @staticmethod
        def decode(val):
            aa = []
            if val[0]:
                aa.append(Action.up)
            if val[1]:
                aa.append(Action.down)
            if val[2]:
                aa.append(Action.left)
            if val[3]:
                aa.append(Action.right)
            return ListSpace(aa)

    class DiscreteDistributionProxy:
        @staticmethod
        def initialize():
            # Don't use "[] * 4" operator since it does not deep copy the pairs but rather
            # copy 4 times the pointers to the same object!
            return [
                [GridShmProxy.StateProxy.initialize(), mp.Value("d", 0, lock=True)],
                [GridShmProxy.StateProxy.initialize(), mp.Value("d", 0, lock=True)],
                [GridShmProxy.StateProxy.initialize(), mp.Value("d", 0, lock=True)],
                [GridShmProxy.StateProxy.initialize(), mp.Value("d", 0, lock=True)],
            ]

        @staticmethod
        def encode(dd, shm_dd):
            for i, o in enumerate(dd.get_values()):
                GridShmProxy.StateProxy.encode(o[0], shm_dd[i][0])
                shm_dd[i][1].value = o[1]
            for i in range(len(dd.get_values()), 4):
                shm_dd[i][1].value = -1

        @staticmethod
        def decode(dd):
            return DiscreteDistribution(
                [
                    (GridShmProxy.StateProxy.decode(o[0]), o[1].value)
                    for o in dd
                    if o[1].value > -0.5
                ]
            )

    class ValueProxy:
        @staticmethod
        def initialize():
            return [mp.Value("d", 0), mp.Value("b", False)]

        @staticmethod
        def encode(value, shm_value):
            if value.reward is not None:
                shm_value[0].value = value.reward
                shm_value[1].value = True
            elif value.cost is not None:
                shm_value[0].value = value.cost
                shm_value[1].value = False
            else:
                shm_value[0].value = 0
                shm_value[1].value = True

        @staticmethod
        def decode(value):
            if value[1].value:
                return Value(reward=value[0].value)
            else:
                return Value(cost=value[0].value)

    class EnvironmentOutcomeProxy:
        @staticmethod
        def initialize():
            return (
                [GridShmProxy.StateProxy.initialize()]
                + GridShmProxy.ValueProxy.initialize()
                + [GridShmProxy.BoolProxy.initialize()]
            )

        @staticmethod
        def encode(outcome, shm_outcome):
            GridShmProxy.StateProxy.encode(outcome.observation, shm_outcome[0])
            GridShmProxy.ValueProxy.encode(outcome.value, shm_outcome[1:3])
            GridShmProxy.BoolProxy.encode(outcome.termination, shm_outcome[3])

        @staticmethod
        def decode(outcome):
            return EnvironmentOutcome(
                observation=GridShmProxy.StateProxy.decode(outcome[0]),
                value=GridShmProxy.ValueProxy.decode(outcome[1:3]),
                termination=GridShmProxy.BoolProxy.decode(outcome[3]),
            )

    class TransitionOutcomeProxy:
        @staticmethod
        def initialize():
            return (
                [GridShmProxy.StateProxy.initialize()]
                + GridShmProxy.ValueProxy.initialize()
                + [GridShmProxy.BoolProxy.initialize()]
            )

        @staticmethod
        def encode(outcome, shm_outcome):
            GridShmProxy.StateProxy.encode(outcome.state, shm_outcome[0])
            GridShmProxy.ValueProxy.encode(outcome.value, shm_outcome[1:3])
            GridShmProxy.BoolProxy.encode(outcome.termination, shm_outcome[3])

        @staticmethod
        def decode(outcome):
            return TransitionOutcome(
                state=GridShmProxy.StateProxy.decode(outcome[0]),
                value=GridShmProxy.ValueProxy.decode(outcome[1:3]),
                termination=GridShmProxy.BoolProxy.decode(outcome[3]),
            )

    class BoolProxy:
        @staticmethod
        def initialize():
            return mp.Value("b", False)

        @staticmethod
        def encode(val, shm_val):
            shm_val.value = val

        @staticmethod
        def decode(val):
            return bool(val.value)

    class FloatProxy:
        @staticmethod
        def initialize():
            return mp.Value("d", False)

        @staticmethod
        def encode(val, shm_val):
            shm_val.value = val

        @staticmethod
        def decode(val):
            return float(val.value)

    class IntProxy:
        @staticmethod
        def initialize():
            return mp.Value("i", False)

        @staticmethod
        def encode(val, shm_val):
            shm_val.value = val

        @staticmethod
        def decode(val):
            return int(val.value)


if __name__ == "__main__":

    try_solvers = [
        # LRTDP
        {
            "name": "LRTDP",
            "entry": "LRTDP",
            "config": {
                "domain_factory": lambda: MyDomain(),
                "heuristic": lambda d, s: Value(
                    cost=sqrt((d.num_cols - 1 - s.x) ** 2 + (d.num_rows - 1 - s.y) ** 2)
                ),
                "use_labels": True,
                "time_budget": 60000,
                "rollout_budget": 10000,
                "max_depth": 50,
                "discount": 1.0,
                "epsilon": 0.001,
                "online_node_garbage": True,
                "continuous_planning": False,
                "parallel": True,
                "verbose": False,
            },
        },
        # ILAO*
        {
            "name": "Improved-LAO*",
            "entry": "ILAOstar",
            "config": {
                "domain_factory": lambda: MyDomain(),
                "heuristic": lambda d, s: Value(
                    cost=sqrt((d.num_cols - 1 - s.x) ** 2 + (d.num_rows - 1 - s.y) ** 2)
                ),
                "discount": 1.0,
                "epsilon": 0.001,
                "parallel": True,
                "verbose": False,
            },
        },
        # UCT-Distribution (reinforcement learning / search)
        {
            "name": "UCT (reinforcement learning / search)",
            "entry": "UCT",
            "config": {
                "domain_factory": lambda: MyDomain(),
                "time_budget": 1000,
                "rollout_budget": 100,
                "max_depth": 50,
                "ucb_constant": 1.0 / sqrt(2.0),
                "transition_mode": MCTS.TransitionMode.DISTRIBUTION,
                "online_node_garbage": True,
                "continuous_planning": False,
                "heuristic": lambda d, s: (
                    Value(
                        cost=sqrt(
                            (d.num_cols - 1 - s.x) ** 2 + (d.num_rows - 1 - s.y) ** 2
                        )
                    ),
                    10000,
                ),
                "parallel": True,
                "verbose": False,
            },
        },
    ]

    # Load solvers (filtering out badly installed ones)
    solvers = map(
        lambda s: dict(s, entry=load_registered_solver(s["entry"])), try_solvers
    )
    solvers = list(filter(lambda s: s["entry"] is not None, solvers))

    # Run loop to ask user input
    domain = MyDomain()  # MyDomain(5,5)

    with tqdm(total=len(solvers) * 100) as pbar:
        for s in solvers:
            solver_type = s["entry"]
            for i in range(50):
                s["config"]["shared_memory_proxy"] = None
                with solver_type(**s["config"]) as solver:
                    solver.solve()
                    rollout(
                        domain,
                        solver,
                        max_steps=50,
                        outcome_formatter=lambda o: f"{o.observation} - cost: {o.value.cost:.2f}",
                    )
                pbar.update(1)
            for i in range(50):
                s["config"]["shared_memory_proxy"] = GridShmProxy()
                with solver_type(**s["config"]) as solver:
                    solver.solve()
                    rollout(
                        domain,
                        solver,
                        max_steps=50,
                        outcome_formatter=lambda o: f"{o.observation} - cost: {o.value.cost:.2f}",
                    )
                pbar.update(1)
