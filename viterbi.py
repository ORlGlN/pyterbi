# jon klein
# kleinjt@ieee.org
# mit license 

# viterbi algorithim, in pycuda and python

# obs       - observations                      [sample]
# states    - states                            [state] 
# init_p    - initial log probabilities         [state]
# trans_p   - transition log probabilities      [prev][current]
# emit_p    - output log probabilities          [emission][state]
# path_p    - initial and final path prob       [state]

import pdb 
import pycuda.tools
import pycuda.autoinit
import pycuda.driver as cuda
from pycuda.compiler import SourceModule
import numpy
import sys
import pp
import matplotlib.pyplot as plt

def main():
    trellises = 4 
    cores = 2
    times = speedup_calc(16,4,4,trellises,cores)
    print 'it worked! speedup due to parallelism:', times

    
def benchmark_multitrellis():
    pass

def benchmark_singletrellis():
    trellises = 4;
    cores = 2;
    nobs = [pow(2,i) for i in range(4,12)];
    noutputs = 32;
    nstates = [pow(2,i) for i in range(1,7)]
    speedup = [[speedup_calc(o, noutputs, n, trellises, cores) for n in nstates] for o in nobs]
    f = plt.figure()

    plots = [plt.plot(nstates, s) for s in speedup]
    plt.legend(plots, nobs,title='observations',bbox_to_anchor=(1.10,1))
    plt.xlabel('number of states')
    plt.ylabel('speedup over host only implementation')
    plt.title('speedup of PyCUDA pyterbi over host only viterbi decoder\n32 outputs, variable number of states and observations lengths\nCPU: i5-2520M, GPU: NVS4200M')
    plt.grid(True)
    plt.savefig('speedup_graph.png')
    plt.show()

def speedup_calc(nobs, noutputs, nstates, ntrellises, hostcores):
    trellises = []

    for i in range(ntrellises):
        trellises.append(Trellis(nobs, noutputs, nstates))
    
    start = cuda.Event()
    end = cuda.Event()
   
    # benchmark host path with an arbitrary number of host cores
    start.record() 
    run_hostviterbi(trellises, hostcores)
    end.record()
    end.synchronize()
    host_time = start.time_till(end) * 1e-3
   
    # benchmark host path with 1 host core, reference implementation
    start.record()
    run_hostviterbi(trellises, 1)
    end.record()
    end.synchronize()
    ref_time = start.time_till(end) * 1e-3

     
    # benchmark cuda path
    start.record()
    viterbi_cuda(trellises)
    end.record()
    end.synchronize()
    cuda_time = start.time_till(end) * 1e-3
    
    # report on results
    for t in trellises:
        if(t.checkroutes()):
            pass
        else:
            print 'host and cuda paths do *NOT* match!'

    return [ref_time/host_time, ref_time/cuda_time]

def run_hostviterbi(trellises, hostcores):
    job_server = pp.Server(ncpus=hostcores)
    jobs = []
    
    for t in trellises:
        jobs.append(t.get_ppjob(job_server))
    
    job_server.wait()
    
    for i in range(len(trellises)):
        j = jobs[i];
        t = trellises[i];
        t.routes.append(j())

# I'm trying to pretend this is a struct...
class Trellis:
    def __init__(self, nobs, noutputs, nstates):
        self.states = numpy.array(range(nstates))
        self.obs = numpy.array(numpy.random.randint(noutputs,size=nobs),dtype=numpy.int16)
        
        self.init_p = numpy.random.rand(nstates)
        self.init_p = numpy.log(numpy.array((self.init_p/sum(self.init_p)),dtype=numpy.float32))
        
        self.trans_p = numpy.random.rand(nstates,nstates)
        self.trans_p = numpy.transpose(self.trans_p / sum(self.trans_p))
        self.trans_p = numpy.log(numpy.array(self.trans_p, dtype=numpy.float32))
    
        self.emit_p = numpy.random.rand(nstates,noutputs)
        self.emit_p = numpy.transpose(self.emit_p / sum(self.emit_p))
        self.emit_p = numpy.log(numpy.array(self.emit_p, dtype=numpy.float32))
        
        self.routes = []

    def checkroutes(self):
        for i in range(1,len(self.routes)):
            if(not numpy.array_equal(self.routes[i],self.routes[0])):
                return False
        return True

    def get_ppjob(self, server):
        return server.submit(viterbi_host, (self.obs, self.states, self.init_p, self.trans_p, self.emit_p,),(viterbi_backtrace,),("numpy",))


def viterbi_host(obs, states, init_p, trans_p, emit_p):
    nobs = len(obs)
    nstates = len(states)
    path_p = numpy.zeros((nobs,nstates), dtype=numpy.float32)
    back = numpy.zeros((nobs,nstates), dtype=numpy.int16)

    # set inital probabilities and path
    path_p[0,:] = init_p + emit_p[obs[0]]
    back[0,:] = states

    for n in range(1, nobs):
        for m in states:
            p = emit_p[obs[n]][m] + trans_p[:,m] + path_p[n-1]
            back[n][m] = numpy.argmax(p)
            path_p[n][m] = numpy.amax(p)

    route = viterbi_backtrace(nobs, path_p, back)
    return route

def viterbi_cuda(trellises):
    viterbi_cuda_gpu = mod.get_function("viterbi_cuda")
   
    # all trellises must be the same length/width
    noutputs = len(trellises[0].emit_p[:,0])
    nstates = len(trellises[0].states)
    nobs = len(trellises[0].obs)
    ntrellises = len(trellises)

    nstates_gpu = numpy.int16(nstates)
    nobs_gpu = numpy.int16(nobs)
        
    
    path_p = numpy.zeros((nstates,ntrellises), dtype=numpy.float32)
    back = numpy.zeros((nobs,nstates,ntrellises), dtype=numpy.int16)
    emit_p = numpy.zeros((noutputs,nstates,ntrellises), dtype=numpy.float32)
    trans_p = numpy.zeros((nstates,nstates,ntrellises), dtype=numpy.float32)
    obs = numpy.zeros((nobs,ntrellises), dtype=numpy.int16)

    for i in range(ntrellises):
        back[0,:,i] = trellises[i].states
        emit_p[:,:,i] = trellises[i].emit_p
        trans_p[:,:,i] = trellises[i].trans_p
        obs[:,i] = trellises[i].obs
        path_p[:,i] = trellises[i].init_p + trellises[i].emit_p[trellises[i].obs[0],i]

    # allocate and copy arrays to device global memory
    emit_p_gpu = cuda.mem_alloc(emit_p.nbytes) 
    cuda.memcpy_htod(emit_p_gpu, emit_p)

    trans_p_gpu = cuda.mem_alloc(trans_p.nbytes) 
    cuda.memcpy_htod(trans_p_gpu, trans_p)
    
    obs_gpu = cuda.mem_alloc(obs.nbytes)
    cuda.memcpy_htod(obs_gpu, obs) 

    path_p_gpu = cuda.mem_alloc(path_p.nbytes)
    cuda.memcpy_htod(path_p_gpu, path_p)
    
    back_gpu = cuda.mem_alloc(back.nbytes)
    cuda.memcpy_htod(back_gpu, back)
    
    viterbi_cuda_gpu(obs_gpu, trans_p_gpu, emit_p_gpu, path_p_gpu, back_gpu, nstates_gpu, nobs_gpu, block=(nstates,1,1),grid=(ntrellises,1))

    
    cuda.memcpy_dtoh(path_p, path_p_gpu)
    cuda.memcpy_dtoh(back, back_gpu)
    
    for i in range(ntrellises):
        t = trellises[i]
        t.path_p = path_p[:,i]
        t.back = back[:,:,i]
        t.routes.append(viterbi_cudabacktrace(nobs, t.path_p, t.back))

# parallelize me!
def viterbi_cudabacktrace(nobs, path_p, back):
    route = numpy.zeros((nobs,1),dtype=numpy.int16)
    route[-1] = numpy.argmax(path_p)
    
    for n in range(2,nobs+1):
        route[-n] = back[nobs-n+1,route[nobs-n+1]]
    return route

def viterbi_backtrace(nobs, path_p, back):
    route = numpy.zeros((nobs,1),dtype=numpy.int16)
    route[-1] = numpy.argmax(path_p[-1,:])

    for n in range(2,nobs+1):
        route[-n] = back[nobs-n+1,route[nobs-n+1]]
    return route

mod = SourceModule("""
#include <stdio.h> 

#define MAX_OBS 1024 
#define MAX_STATES 32
#define MAX_OUTS 32

__global__ void viterbi_cuda(short *obs, float *trans_p, float *emit_p, float *path_p, short *back, short nstates, short nobs)
{
    
    const int tx = threadIdx.x;
    short i, j, ipmax;
     
    __shared__ float emit_p_s[MAX_OUTS * MAX_STATES];
    __shared__ float trans_p_s[MAX_STATES * MAX_STATES];
    __shared__ float path_p_s[MAX_STATES];
    __shared__ float path_p_s_n[MAX_STATES];

    for(i = 0; i < MAX_OUTS; i++) {
        emit_p_s[tx + i*nstates] = emit_p[tx + i*nstates];
    }

   
    for(i = 0; i < nstates; i++) {
        trans_p_s[tx + nstates * i] = trans_p[tx + nstates * i];
    }
    
    path_p_s_n[tx] = path_p[tx];

    // I only need to maintain a slice of path_p and it could remain in shared memory, this would reduce memory accesses by quite a bit
    for(j = 1; j < nobs; j++) {
        path_p_s[tx] = path_p_s_n[tx];
        __syncthreads();
 
        float pmax = logf(0);
        float pt = 0; 
        ipmax = 0;

        for(i = 0; i < nstates; i++) {
            pt = emit_p_s[obs[j]*nstates+tx] + trans_p_s[i*nstates+tx] + path_p_s[i];
            if(pt > pmax) {
                ipmax = i;
                pmax = pt;
            }
        }
    
        path_p_s_n[tx] = pmax;
        back[j*nstates+tx] = ipmax;
        __syncthreads();
    }
    
}
""")

if __name__ == "__main__":
    main()
