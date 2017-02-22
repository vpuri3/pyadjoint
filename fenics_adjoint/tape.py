import backend


_working_tape = None

def get_working_tape():
    return _working_tape

def set_working_tape(tape):
    global _working_tape
    _working_tape = tape

class Tape(object):

    __slots__ = ["blocks"]

    def __init__(self):
        # Initialize the list of blocks on the tape.
        self.blocks = []

    def clear_tape(self):
        self.reset_variables()
        self.blocks = []

    def add_block(self, block):
        """
        Adds a block to the tape and returns the index.
        """
        self.blocks.append(block)

        # len() is computed in constant time, so this should be fine.
        return len(self.blocks)-1

    def evaluate(self):
        for i in range(len(self.blocks)-1, -1, -1):
            self.blocks[i].evaluate_adj()

    def reset_variables(self):
        for i in range(len(self.blocks)-1, -1, -1):
            self.blocks[i].reset_variables()

class Block(object):
    """Base class for all Tape Block types.
    
    Each instance of a Block type represents an elementary operation in the forward model.
    
    Abstract methods:
        evaluate_adj

    Attributes:
        dependencies (set) : a set containing the inputs in the forward model
        fwd_outputs (list) : a list of outputs in the forward model

    """
    def __init__(self):
        self.dependencies = set()
        self.fwd_outputs = []

    def add_dependency(self, dep):
        self.dependencies.add(dep.get_block_output())

    def get_dependencies(self):
        return self.dependencies

    def create_fwd_output(self, obj):
        self.fwd_outputs.append(obj)

    def reset_variables(self):
        for dep in self.dependencies:
            dep.reset_variables()

    def create_reference_object(self, output):
        if isinstance(output, float):
            cls = AdjFloat
        elif isinstance(output, backend.Function):
            cls = Function
        else:
            raise NotImplementedError

        ret = cls(output)
        self.create_fwd_output(ret.get_block_output())

        return ret

    def evaluate_adj():
        raise NotImplementedError

class BlockOutput(object):
    def __init__(self, output):
        self.output = output
        self.adj_value = 0
        self.saved_output = None

    def add_adj_output(self, val):
        self.adj_value += val

    def get_adj_output(self):
        #print "Bugger ut: ", self.adj_value
        #print self.output
        return self.adj_value

    def set_initial_adj_input(self, value):
        self.adj_value = value

    def reset_variables(self):
        self.adj_value = 0

    def get_output(self):
        return self.output

    def save_output(self):
        self.saved_output = Function(self.output.function_space(), self.output.vector())

    def get_saved_output(self):
        if self.saved_output:
            return self.saved_output
        else:
            return self.output

class OverloadedType(object):
    def __init__(self, *args, **kwargs):
        tape = kwargs.pop("tape", None)

        if tape:
            self.tape = tape
        else:
            self.tape = get_working_tape()

        self.original_block_output = self.create_block_output()

    def create_block_output(self):
        block_output = BlockOutput(self)
        self.set_block_output(block_output)
        return block_output

    def set_block_output(self, block_output):
        self.block_output = block_output

    def get_block_output(self):
        return self.block_output

    def get_adj_output(self):
        return self.original_block_output.get_adj_output()

    def set_initial_adj_input(self, value):
        self.block_output.set_initial_adj_input(value)

    def reset_variables(self):
        self.original_block_output.reset_variables()


class Function(OverloadedType, backend.Function):
    def __init__(self, *args, **kwargs):
        super(Function, self).__init__(*args, **kwargs)
        backend.Function.__init__(self, *args, **kwargs)

    def assign(self, other, *args, **kwargs):
        self.get_block_output().save_output()
        self.set_block_output(other.get_block_output())
        self.get_block_output().output = self

        return super(Function, self).assign(other, *args, **kwargs)

class Constant(OverloadedType, backend.Constant):
    def __init__(self, *args, **kwargs):
        super(Constant, self).__init__(*args, **kwargs)
        backend.Constant.__init__(self, *args, **kwargs)

class DirichletBC(OverloadedType, backend.DirichletBC):
    def __init__(self, *args, **kwargs):
        super(DirichletBC, self).__init__(*args, **kwargs)
        backend.DirichletBC.__init__(self, *args, **kwargs)

class AdjFloat(OverloadedType, float):
    def __new__(cls, *args, **kwargs):
        return float.__new__(cls, *args)

    def __init__(self, *args, **kwargs):
        super(AdjFloat, self).__init__(*args, **kwargs)
        float.__init__(self, *args, **kwargs)

    def __mul__(self, other):
        output = float.__mul__(self, other)
        if output is NotImplemented:
            return NotImplemented

        block = AdjFloat.MulBlock(self.tape, self, other)
        output = block.create_reference_type(output)
        return output 


    class MulBlock(Block):
        def __init__(self, lfactor, rfactor):
            super(MulBlock, self).__init__()
            self.lfactor = lfactor
            self.rfactor = rfactor

        def evaluate_adj(self):
            adj_input = self.fwd_outputs[0].get_adj_output()

            self.rfactor.add_adj_output(adj_input * self.lfactor)
            self.lfactor.add_adj_output(adj_input * self.rfactor)