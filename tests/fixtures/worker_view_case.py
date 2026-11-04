"""Native IPC must transport CPU storage slices, offsets and noncontiguous views."""
class Views:
    def run(self,x):
        return {'slice':x[1:],'offset':x[:,:,1:],'transpose':x.transpose(1,2),
                'broadcast':x[:1].expand(4,-1,-1),'empty_view':x[:0],'owned_empty':x.new_empty((0,4,5))}

    def echo(self,x):
        return x
