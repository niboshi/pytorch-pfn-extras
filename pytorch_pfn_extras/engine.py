from typing import (
    Any, Callable, Dict, List, Optional, Tuple, Type, Union, TYPE_CHECKING
)

import torch

import pytorch_pfn_extras.handler as handler_module
from pytorch_pfn_extras.runtime import runtime_registry

if TYPE_CHECKING:
    from pytorch_pfn_extras._runtime import DeviceLike
    from pytorch_pfn_extras import training
    from pytorch_pfn_extras.training.trigger import TriggerLike
    from pytorch_pfn_extras.training._trainer import _Trainer
    from pytorch_pfn_extras.training._evaluator import _Evaluator
    from pytorch_pfn_extras.training.metrics import MetricType
    from pytorch_pfn_extras import writing


class _Engine:
    def __init__(
            self,
            handler: handler_module.BaseHandler,
            models: Union[torch.nn.Module, Dict[str, torch.nn.Module]],
            **kwargs: Any,
    ) -> None:
        self.handler = handler
        self._manager: Optional['training.ExtensionsManager'] = None

        # The followings are used when setting up a manager instance
        if not isinstance(models, dict):
            if not isinstance(models, torch.nn.Module):
                raise ValueError(
                    'model must be an instance of dict or toch.nn.Module')
            self._models = {'main': models}
        else:
            self._models = models
        self._kwargs = kwargs
        self._extensions: List[  # list of (args, kwargs)
            Tuple[Tuple['training.Extension', Optional[str],
                        'TriggerLike', Optional[int]],
                  Dict[str, Any]]] = []
        self._manager_state: Optional[Dict[str, Any]] = None

    def extend(
            self,
            extension: 'training.Extension',
            name: Optional[str] = None,
            trigger: 'TriggerLike' = None,
            priority: Optional[int] = None,
            *,
            call_before_training: bool = False,
            **kwargs: Any,
    ) -> None:
        if self._manager is not None:
            raise RuntimeError('cannot extend after starting the engine')
        self._extensions.append(
            ((extension, name, trigger, priority),
             dict(call_before_training=call_before_training, **kwargs)))

    def _setup_manager(self, iters_per_epoch: int) -> None:
        from pytorch_pfn_extras.training import ExtensionsManager
        self._manager = ExtensionsManager(
            self._models, iters_per_epoch=iters_per_epoch, **self._kwargs)
        for ex_args, ex_kwargs in self._extensions:
            self._manager.extend(*ex_args, **ex_kwargs)
        if self._manager_state is not None:
            self.manager.load_state_dict(self._manager_state)

    @property
    def manager(self) -> 'training.ExtensionsManager':
        if self._manager is None:
            raise RuntimeError('the engine is not started yet')
        return self._manager

    @property
    def models(self) -> Dict[str, torch.nn.Module]:
        # TODO(kmaehashi): do we need this convenient interface for handlers?
        return self.manager.raw_models

    @property
    def optimizers(self) -> Dict[str, torch.optim.Optimizer]:
        return self.manager.optimizers

    def state_dict(self) -> Dict[str, Any]:
        return self.manager.state_dict()

    def load_state_dict(self, to_load: Dict[str, Any]) -> None:
        if self._manager is None:
            self._manager_state = to_load
            return
        self.manager.load_state_dict(to_load)

    def run(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError


def create_trainer(
        models: Union[torch.nn.Module, Dict[str, torch.nn.Module]],
        optimizers: Dict[str, torch.optim.Optimizer],
        max_epochs: int,
        *,
        extensions: Optional[List['training.Extension']] = None,
        out_dir: str = 'result',
        stop_trigger: 'TriggerLike' = None,
        writer: Optional['writing.Writer'] = None,
        evaluator: Optional['_Evaluator'] = None,
        device: 'DeviceLike' = 'cpu',
        options: Optional[Dict[str, Any]] = None,
        logic: Optional[handler_module.Logic] = None,
        transform_model: Callable[
            [str, torch.nn.Module], torch.nn.Module] = lambda n, x: x,
        handler_class: Optional[Type[handler_module.BaseHandler]] = None,
) -> '_Trainer':
    """Creates a trainer object.

    Args:
        models: (dict or torch.nn.Module):
            Map of string to Module or an actual Module.
        optimizers (dict or torch.optim.Optimizer):
            Map of string to Optimizer or an actual Optimizer.
        max_epochs (int):
            Number of epochs in the whole training loop.
            Ignored if `stop_trigger` is passed as a kwarg.
        extensions (list of Extension, optional):
            List of extensions to be registered to the trainer.
        out_dir (str):
            Output directory (default: ``result``).
        stop_trigger (trigger object, optional):
            Trigger that can be consulted to determine wether training has
            concluded. The default is an interval trigger set to `max_epochs`
        writer (writing.Writer, optional):
            Writer that can be used by extensions to write data to custom
            filesystems.
        evaluator (Evaluator, optional):
            Evaluator that is used in evaluation phase.
            If `None` is given, the evaluation is skipped.
        device (str or torch.device):
            Device name used for selecting a corresponding runtime class.
        options (dict):
            Option that is set to a logic object. When using the default logic
            class, See the documentation of `ppe.handler.Logic` for details.
        logic (logic object):
            A logic object. If `None` is given, an logic object is instantiated
            from the default logic class.
        handler_class (handler class):
            A handler class that instantiates a handler object. If `None` is
            given, `ppe.handler.Handler` is used as a default handler class.
    """

    if options is None:
        options = {}
    else:
        options = options.copy()
    if logic is None:
        logic = handler_module.Logic()
    logic.set_options(options)
    if handler_class is None:
        handler_class = handler_module.Handler

    entry_runtime_cls = runtime_registry.get_runtime_class_for_device_spec(
        device)
    entry_runtime = entry_runtime_cls(device, options.pop('runtime', {}))
    handler = handler_class(logic, entry_runtime, options)
    if len(options) > 0:
        raise ValueError('Unknown configuration options:', options)

    from pytorch_pfn_extras.training._trainer import _Trainer
    return _Trainer(
        handler, evaluator=evaluator,
        models=models, optimizers=optimizers, max_epochs=max_epochs,
        extensions=extensions, out_dir=out_dir,
        stop_trigger=stop_trigger, writer=writer,
        transform_model=transform_model,
    )


def create_evaluator(
        models: Union[torch.nn.Module, Dict[str, torch.nn.Module]],
        *,
        progress_bar: bool = False,
        device: 'DeviceLike' = 'cpu',
        metrics: Optional[List['MetricType']] = None,
        options: Optional[Dict[str, Any]] = None,
        logic: Optional[handler_module.Logic] = None,
        handler_class: Optional[Type[handler_module.BaseHandler]] = None,
) -> '_Evaluator':
    """Creates a trainer object. the return value of this function is expected
    to be fed to `ppe.engine.create_trainer` as an argument.

    Args:
        models: (dict or torch.nn.Module):
            Map of string to Module or an actual Module. In most cases,
            this arugment is the same as the `model` arguemnt of
            `ppe.engine.create_trainer`.
        progress_bar (bool):
            If `True`, a progress bar is enabled in evaluation.
        device (str or torch.device):
            Device name used for selecting a corresponding runtime class.
        metrics (list of metrics):
            List of metrics, which computes various quantities and update
            output for the reporting.
        options (dict):
            Option that is set to a logic object. When using the default logic
            class, See the documentation of `ppe.handler.Logic` for details.
        logic (logic object):
            A logic object. If `None` is given, an logic object is instantiated
            from the default logic class.
        handler_class (handler class):
            A handler class that instantiates a handler object. If `None` is
            given, `ppe.handler.Handler` is used as a default handler class.
    """

    if metrics is None:
        metrics = []
    if options is None:
        options = {}
    else:
        options = options.copy()
    if logic is None:
        logic = handler_module.Logic()
    logic.set_options(options)
    if handler_class is None:
        handler_class = handler_module.Handler

    entry_runtime_cls = runtime_registry.get_runtime_class_for_device_spec(
        device)
    entry_runtime = entry_runtime_cls(device, options.pop('runtime', {}))
    handler = handler_class(logic, entry_runtime, options)

    if len(options) > 0:
        raise ValueError('Unknown configuration options ', options)

    from pytorch_pfn_extras.training._evaluator import _Evaluator
    return _Evaluator(
        handler,
        models=models,
        progress_bar=progress_bar,
        metrics=metrics,
    )
