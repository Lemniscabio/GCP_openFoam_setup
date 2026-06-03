// Mirrors core/config.MACHINE_CATALOG (c2d-highcpu only, 2GB/vCPU).
export type Machine = { name: string; vcpus: number; memGiB: number; mpi: number };

export const MACHINES: Machine[] = [2, 4, 8, 16, 32, 56, 112].map((v) => ({
  name: `c2d-highcpu-${v}`,
  vcpus: v,
  memGiB: v * 2,
  mpi: Math.max(1, Math.floor(v / 2)),
}));
