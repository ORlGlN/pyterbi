# jon klein
# kleinjt@ieee.org
# mit license

# viterbi algorithim, in pycuda and python
# course project for parallel computing class
# obs       - observations                      [sample]
# states    - states                            [state] 
# init_p    - initial log probabilities         [state]
# trans_p   - transition log probabilities      [prev][current]
# emit_p    - output log probabilities          [emission][state]

import pdb 
import pycuda.tools
import pycuda.autoinit
import pycuda.driver as cuda
from pycuda.compiler import SourceModule
import numpy as np 
import sys


nobs = 1000 
noutputs = 20 
nstates = 30

def main():
    start = cuda.Event()
    end = cuda.Event()
    
    states = np.array(range(nstates))
    obs = np.array(np.random.randint(noutputs,size=nobs),dtype=np.int32)

    init_p = np.random.rand(nstates)
    init_p = np.log(np.array((init_p/sum(init_p)),dtype=np.float32))
    
    trans_p = np.random.rand(nstates,nstates)
    trans_p = np.transpose(trans_p / sum(trans_p))
    trans_p = np.log(np.array(trans_p, dtype=np.float32))

    emit_p = np.random.rand(nstates,noutputs)
    emit_p = np.transpose(emit_p / sum(emit_p))
    emit_p = np.log(np.array(emit_p, dtype=np.float32))

    start.record() 
    route_host, path_host, back_host = viterbi_host(obs, states, init_p, trans_p, emit_p)
    end.record()
    end.synchronize()
    host_time = start.time_till(end) * 1e-3
   
    start.record()
    route_cu, path_cu, back_cu = viterbi_cuda(obs, states, init_p, trans_p, emit_p)
    end.record()
    end.synchronize()
    cuda_time = start.time_till(end) * 1e-3

    if (np.array_equal(route_cu, route_host)):
        print 'host and cuda paths match'
    else:
        print 'host and cuda paths do *NOT* match!'
        pdb.set_trace()

    print 'cuda execution time: ', cuda_time
    print 'host execution time: ', host_time
    print 'speedup in cuda path: ', host_time/cuda_time

def viterbi_host(obs, states, init_p, trans_p, emit_p):
    # create negative infinity probability matrix
    nobs = len(obs)
    nstates = len(states)
    
    # track path through trellis
    path_p = np.zeros((nobs,nstates), dtype=np.float32)
    back = np.zeros((nobs,nstates), dtype=np.int32)

    # set inital probabilities and path
    path_p[0,:] = init_p + emit_p[obs[0]]
    back[0,:] = states

    for n in range(1, nobs):
        for m in states: # parallelize this:
            p = emit_p[obs[n]][m] + trans_p[:,m] + path_p[n-1]
            back[n][m] = np.argmax(p)
            path_p[n][m] = np.amax(p)  

    route = np.zeros((nobs,1),dtype=np.int32)
    route[-1] = np.argmax(path_p[-1,:])
    
    # backtrace to find likely route
    for n in range(2,nobs+1):
        route[-n] = back[nobs-n+1,route[nobs-n+1]]
    
    return route, path_p, back


def viterbi_cuda(obs, states, init_p, trans_p, emit_p):
    # create negative infinity probability matrix
    nobs = len(obs)
    nstates = len(states)
    
    # track path through trellis
    path_p = np.zeros((nobs,nstates), dtype=np.float32)
    back = np.zeros((nobs,nstates), dtype=np.int32)

    # set inital probabilities and path
    path_p[0,:] = init_p + emit_p[obs[0]]
    back[0,:] = states

    # copy constant arrays to device memory (emit_p, trans_p, obs)
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

    viterbi_cuda = mod.get_function("viterbi_cuda")

    nstates_gpu = np.int32(len(states))
    
    # calculate viterbi steps
    for n in np.arange(1, nobs, dtype=np.uint32):
        viterbi_cuda(obs_gpu, trans_p_gpu, emit_p_gpu, path_p_gpu, back_gpu, n, nstates_gpu, block=(nstates,1,1));

    cuda.memcpy_dtoh(back, back_gpu)
    cuda.memcpy_dtoh(path_p, path_p_gpu);
    route = np.zeros((nobs,1),dtype=np.int32)
    route[-1] = np.argmax(path_p[-1,:])
  
    # backtrace to find likely route
    for n in range(2,nobs+1):
        route[-n] = back[nobs-n+1,route[nobs-n+1]]
    
    return route, path_p, back

mod = SourceModule("""
#include <stdio.h> 

__global__ void viterbi_cuda(int *obs, float *trans_p, float *emit_p, float *path_p, int *back, int tick, int nstates)
{
    const int tx = threadIdx.x;
    const int ty = threadIdx.y; 
    
    const int bx = blockIdx.x; 
    const int by = blockIdx.y;

    int i, ipmax;

    float pmax = logf(0);
    float pt = 0; 
    ipmax = 0;

    for(i = 0; i < nstates; i++)
    {
        pt = emit_p[obs[tick]*nstates+tx] + trans_p[i*nstates+tx] + path_p[(tick-1)*nstates+i];
        if(pt > pmax) {
            ipmax = i;
            pmax = pt;
        }
    }
    
    path_p[tick*nstates+tx] = pmax;
    back[tick*nstates+tx] = ipmax;
    
    __syncthreads();
}
""")

if __name__ == "__main__":
    main()