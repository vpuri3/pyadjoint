import backend
from pyadjoint.tape import get_working_tape, no_annotations
from pyadjoint.overloaded_type import OverloadedType
from .compat import constant_function_firedrake_compat
from pyadjoint.block import Block

import numpy


class Constant(OverloadedType, backend.Constant):
    def __init__(self, *args, **kwargs):
        super(Constant, self).__init__(*args, **kwargs)
        backend.Constant.__init__(self, *args, **kwargs)

    def assign(self, *args, **kwargs):
        from .types import create_overloaded_object

        annotate_tape = kwargs.pop("annotate_tape", True)
        if annotate_tape:
            other = args[0]
            if not isinstance(other, OverloadedType):
                other = create_overloaded_object(other)

            block = AssignBlock(self, other)
            tape = get_working_tape()
            tape.add_block(block)

        ret = backend.Constant.assign(self, *args, **kwargs)

        if annotate_tape:
            block.add_output(self.create_block_variable())

        return ret

    def get_derivative(self, options={}):
        return self._ad_convert_type(self.adj_value, options=options)

    def adj_update_value(self, value):
        self.original_block_variable.checkpoint = value._ad_create_checkpoint()

    def _ad_convert_type(self, value, options={}):
        value = constant_function_firedrake_compat(value)
        return Constant(value)

    def _ad_function_space(self, mesh):
        element = self.ufl_element()
        fs_element = element.reconstruct(cell=mesh.ufl_cell())
        return backend.FunctionSpace(mesh, fs_element)

    def _ad_create_checkpoint(self):
        if self.ufl_shape == ():
            return Constant(self)
        return Constant(self.values())

    def _ad_restore_at_checkpoint(self, checkpoint):
        return checkpoint

    def _ad_mul(self, other):
        values = ufl_shape_workaround(self.values() * other)
        return Constant(values)

    def _ad_add(self, other):
        values = ufl_shape_workaround(self.values() + other.values())
        return Constant(values)

    def _ad_dot(self, other, options=None):
        return sum(self.values()*other.values())

    @staticmethod
    def _ad_assign_numpy(dst, src, offset):
        dst.assign(backend.Constant(numpy.reshape(src[offset:offset + dst.value_size()], dst.ufl_shape)))
        offset += dst.value_size()
        return dst, offset

    @staticmethod
    def _ad_to_list(m):
        a = numpy.zeros(m.value_size())
        p = numpy.zeros(m.value_size())
        m.eval(a, p)
        return a.tolist()

    def _ad_copy(self):
        values = ufl_shape_workaround(self.values())
        return Constant(values)

    def _ad_dim(self):
        return numpy.prod(self.values().shape)

    def _imul(self, other):
        self.assign(ufl_shape_workaround(self.values() * other))

    def _iadd(self, other):
        self.assign(ufl_shape_workaround(self.values() + other.values()))

    def _reduce(self, r, r0):
        npdata = self.values()
        for i in range(len(npdata)):
            r0 = r(npdata[i], r0)
        return r0

    def _applyUnary(self, f):
        npdata = self.values()
        npdatacopy = npdata.copy()
        for i in range(len(npdata)):
            npdatacopy[i] = f(npdata[i])
        self.assign(ufl_shape_workaround(npdatacopy))

    def _applyBinary(self, f, y):
        npdata = self.values()
        npdatacopy = self.values().copy()
        npdatay = y.values()
        for i in range(len(npdata)):
            npdatacopy[i] = f(npdata[i], npdatay[i])
        self.assign(ufl_shape_workaround(npdatacopy))


def ufl_shape_workaround(values):
    """Workaround because of the following behaviour in FEniCS/Firedrake

    c = Constant(1.0)
    c2 = Constant(c2.values())
    c.ufl_shape == ()
    c2.ufl_shape == (1,)

    Thus you will get a shapes don't match error if you try to replace c with c2 in a UFL form.
    Because of this we require that scalar constants in the forward model are all defined with ufl_shape == (),
    otherwise you will most likely see an error.

    Args:
        values: Array of floats that should come from a Constant.values() call.

    Returns:
        A float if the Constant was scalar, otherwise the original array.

    """
    if len(values) == 1:
        return values[0]
    return values


class AssignBlock(Block):
    def __init__(self, func, other):
        super(AssignBlock, self).__init__()
        self.add_dependency(func.block_variable)
        self.add_dependency(other.block_variable)

    def evaluate_adj(self):
        adj_input = self.get_outputs()[0].adj_value
        self.get_dependencies()[1].add_adj_output(adj_input)

    def evaluate_tlm(self):
        tlm_input = self.get_dependencies()[1].tlm_value
        self.get_outputs()[0].add_tlm_output(tlm_input)

    def evaluate_hessian(self):
        hessian_input = self.get_outputs()[0].hessian_value
        self.get_dependencies()[1].add_hessian_output(hessian_input)

    def recompute(self):
        deps = self.get_dependencies()
        other_bo = deps[1]

        backend.Constant.assign(self.get_outputs()[0].saved_output, other_bo.saved_output)

