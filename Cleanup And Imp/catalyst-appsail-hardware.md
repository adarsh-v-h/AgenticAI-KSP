# Catalyst AppSail — Hardware/OS Diagnostics

Captured on: July 19, 2026
Source: `GET /api/diagnostics/hardware` (temporary supervisor-only endpoint,
removed after this capture — see `backend/routers/diagnostics.py` history
in git for the removed code).

Container running the deployed backend: `crime-intel-backend` (AppSail).

## Summary

| Category | Value |
|---|---|
| OS | Ubuntu 24.04.4 LTS (Noble Numbat), kernel 6.1.172 |
| CPU | AMD EPYC, 2 logical cores (shared/virtualized — cache size 512 KB per core, `hypervisor` flag present) |
| Memory | ~495 MB total (`MemTotal: 495840 kB`), ~223 MB free at capture time |
| GPU | **None available.** No `nvidia-smi`, no `/dev/nvidia*` device nodes, no NVIDIA kernel driver, no VGA/3D controller detected via `lspci`. |
| Container runtime | Not Docker (`/.dockerenv` absent, no `/proc/1/cgroup`) — Catalyst's own AppSail sandbox (hostname `catalyst`, `/catalyst` overlay mount) |
| Disk | Small, split-purpose mounts: `/` 884M (93% used), `/tmp` 246M, `/var/code` 1006M, `/var/lang` 383M, `/catalyst` overlay 246M |

## Key takeaways

- **No GPU support.** This AppSail instance is CPU-only. Any ML/LLM inference
  that needs local GPU acceleration cannot run here — this is consistent
  with the app's actual architecture, which calls out to Zoho Catalyst
  QuickML (a remote/managed LLM API) rather than running models locally.
- **Very constrained resources**: 2 vCPUs, ~500 MB RAM, under 1 GB root disk.
  This is a small shared-tenancy container, not a dedicated VM — consistent
  with AppSail's serverless/managed nature. Memory-heavy operations (large
  result sets, big file uploads/exports) should stay mindful of this ceiling.
- **AMD EPYC** vCPU with a hypervisor flag confirms this is a virtualized
  slice of a larger physical host, not bare metal.
- Confirms `backend/Dockerfile`'s `--workers 2` setting for uvicorn lines up
  with the actual 2-core allocation — no headroom to raise worker count
  without requesting more resources from Catalyst.

## Raw captured data

```json
{
  "python": {
    "platform": "Linux-6.1.172-x86_64-with-glibc2.39",
    "machine": "x86_64",
    "processor": "x86_64",
    "python_version": "3.10.19"
  },
  "os": {
    "uname": "Linux catalyst 6.1.172 #1 SMP PREEMPT_DYNAMIC Tue May 26 12:06:42 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux",
    "os_release": "PRETTY_NAME=\"Ubuntu 24.04.4 LTS\"\nNAME=\"Ubuntu\"\nVERSION_ID=\"24.04\"\nVERSION=\"24.04.4 LTS (Noble Numbat)\"\nVERSION_CODENAME=noble\nID=ubuntu\nID_LIKE=debian\nHOME_URL=\"https://www.ubuntu.com/\"\nSUPPORT_URL=\"https://help.ubuntu.com/\"\nBUG_REPORT_URL=\"https://bugs.launchpad.net/ubuntu/\"\nPRIVACY_POLICY_URL=\"https://www.ubuntu.com/legal/terms-and-policies/privacy-policy\"\nUBUNTU_CODENAME=noble\nLOGO=ubuntu-logo"
  },
  "cpu": {
    "logical_core_count": 2,
    "cpuinfo_summary": "model name\t: AMD EPYC\n2",
    "cpuinfo_raw_head": "processor\t: 0\nvendor_id\t: AuthenticAMD\ncpu family\t: 25\nmodel\t\t: 1\nmodel name\t: AMD EPYC\nstepping\t: 1\nmicrocode\t: 0x1000065\ncpu MHz\t\t: 2595.124\ncache size\t: 512 KB\nphysical id\t: 0\nsiblings\t: 2\ncore id\t\t: 0\ncpu cores\t: 2\napicid\t\t: 0\ninitial apicid\t: 0\nfpu\t\t: yes\nfpu_exception\t: yes\ncpuid level\t: 16\nwp\t\t: yes\nflags\t\t: fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 ht syscall nx mmxext fxsr_opt pdpe1gb rdtscp lm constant_tsc rep_good nopl nonstop_tsc cpuid extd_apicid tsc_known_freq pni pclmulqdq ssse3 fma cx16 pcid sse4_1 sse4_2 x2apic movbe popcnt tsc_deadline_timer aes xsave avx f16c rdrand hypervisor lahf_lm cmp_legacy svm cr8_legacy abm sse4a misalignsse 3dnowprefetch osvw topoext perfctr_core invpcid_single ssbd ibrs ibpb stibp vmmcall fsgsbase tsc_adjust bmi1 avx2 smep bmi2 invpcid rdseed adx smap clflushopt clwb sha_ni xsaveopt xsavec xgetbv1 xsaves clzero xsaveerptr wbnoinvd arat npt lbrv nrip_save tsc_scale vmcb_clean pausefilter pfthreshold v_vmsave_vmload vgif umip pku ospke vaes vpclmulqdq rdpid\nbugs\t\t: sysret_ss_attrs spectre_v1 spectre_v2 spec_store_bypass srso ibpb_no_ret tsa\nbogomips\t: 5190.24\nTLB size\t: 2560 4K pages\nclflush size\t: 64\ncache_alignment\t: 64\naddress sizes\t: 48 bits physical, 48 bits virtual"
  },
  "memory": {
    "meminfo_summary": "MemTotal:         495840 kB\nMemFree:          223648 kB\nMemAvailable:     391372 kB"
  },
  "container": {
    "cgroup_head": "<not present>",
    "dockerenv_present": false,
    "hostname": "catalyst",
    "infra_related_env_var_names": [
      "CATALYST_MAX_TIMEOUT",
      "CATALYST_PROJECT_ID",
      "CATALYST_PROJECT_TIMEZONE",
      "CATALYST_USER_ENVIRONMENT",
      "KSP_CATALYST_ACCOUNTS_URL",
      "KSP_CATALYST_API_TOKEN",
      "KSP_CATALYST_BASE_URL",
      "KSP_CATALYST_CLIENT_ID",
      "KSP_CATALYST_CLIENT_SECRET",
      "KSP_CATALYST_ORG_ID",
      "KSP_CATALYST_PROJECT_ID",
      "KSP_CATALYST_REFRESH_TOKEN",
      "X-ZOHO-CATALYST-ENVIRONMENT",
      "X_ZOHO_CATALYST_ACCOUNTS_URL",
      "X_ZOHO_CATALYST_APPCOMPUTE_DEPLOYMENT_TYPE",
      "X_ZOHO_CATALYST_APPCOMPUTE_STACK",
      "X_ZOHO_CATALYST_CONSOLE_URL",
      "X_ZOHO_CATALYST_ENVIRONMENT",
      "X_ZOHO_CATALYST_LISTEN_PORT",
      "X_ZOHO_CATALYST_RESOURCE_ID",
      "X_ZOHO_CATALYST_RUNTIME_MEMORY",
      "X_ZOHO_CATALYST_SERVER_LISTEN_PORT"
    ]
  },
  "gpu": {
    "nvidia_smi": "<command not found>",
    "dev_nvidia_nodes": "<none found>",
    "proc_driver_nvidia": "<not present>",
    "lspci_vga_3d": "<empty output>",
    "note": "lspci in a container often reflects the HOST's PCI devices, not what's actually passed through to this container — nvidia_smi and dev_nvidia_nodes are the more trustworthy signals for whether THIS container can actually use a GPU."
  },
  "disk": {
    "df_h": "Filesystem      Size  Used Avail Use% Mounted on\n/dev/vda        884M  762M   62M  93% /\ntmpfs           243M     0  243M   0% /dev/shm\nrun             243M  8.0K  243M   1% /run\n/dev/vdb        246M  7.6M  235M   4% /tmp\n/dev/vdc       1006M  107M  883M  11% /var/code\n/dev/vdd        383M  280M   78M  79% /var/lang\noverlay2        246M  7.6M  235M   4% /catalyst"
  }
}
```
