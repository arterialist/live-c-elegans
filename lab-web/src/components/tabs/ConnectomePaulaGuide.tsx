/**
 * PAULA / ALERM reference for the Connectome tab (self-contained copy for the
 * browser — no workspace markdown paths; see blog + GitHub links below).
 */

const URL = {
  paulaPaper: "https://al.arteriali.st/blog/paula-paper",
  alermFramework: "https://al.arteriali.st/blog/alerm-framework",
  neuronModelRepo: "https://github.com/arterialist/neuron-model",
  activeInferenceRepo: "https://github.com/arterialist/active-inference",
} as const;

export function ConnectomePaulaGuide() {
  return (
    <div className="h-full overflow-auto rounded-lg border border-zinc-800/80 bg-zinc-950/40 px-4 py-3 sm:px-5">
      <header className="mb-6 border-b border-zinc-800/80 pb-4">
        <h2 className="text-sm font-semibold tracking-wide text-zinc-200">
          PAULA reference
        </h2>
        <p className="mt-2 max-w-3xl text-[13px] leading-relaxed text-zinc-400">
          PAULA (Predictive Adaptive Unsupervised Learning Agent) is the spiking
          neuron used in this lab&apos;s connectome. PAULA is the concrete neuron
          model in the{" "}
          <ExternalLink href={URL.alermFramework}>ALERM</ExternalLink> framework
          (unified active-inference view of sensing, learning, and action). Below:{" "}
          <strong className="font-medium text-zinc-300">
            (1) static configuration parameters
          </strong>{" "}
          (<code className="text-zinc-400">NeuronParameters</code> and global
          bounds) and{" "}
          <strong className="font-medium text-zinc-300">
            (2) dynamic state, synaptic payloads, tick() phases, and key equations
          </strong>
          . If you know integrate-and-fire units, leaky integrators, and STDP
          windows, this should be enough to map behaviour to what you edit in the
          inspector.
        </p>
        <FurtherReadingIntro />
        <nav className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
          <a className="hover:text-accent" href="#guide-paula-params">
            §1 Parameters
          </a>
          <a className="hover:text-accent" href="#guide-paula-dynamics">
            §2 State &amp; dynamics
          </a>
          <a className="hover:text-accent" href="#guide-paula-refs">
            References
          </a>
        </nav>
      </header>

      {/* ——— Section 1: every NeuronParameters field + global bounds ——— */}
      <section id="guide-paula-params" className="mb-10 scroll-mt-4">
        <h2 className="mb-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Section 1 · Configuration parameters
        </h2>
        <p className="mb-5 max-w-3xl text-[13px] leading-relaxed text-zinc-400">
          Each neuron carries a{" "}
          <code className="text-zinc-400">NeuronParameters</code> dataclass.
          Vector fields (
          <code className="text-zinc-400">gamma</code>,{" "}
          <code className="text-zinc-400">w_r</code>, …) are resized in
          <code className="text-zinc-400"> __post_init__</code> to length{" "}
          <code className="text-zinc-400">num_neuromodulators</code>. Defaults
          below match the published parameter table; per-class presets (sensory
          / interneuron / motor) override them when the connectome is built — see
          the paper and{" "}
          <ExternalLink href={URL.neuronModelRepo}>neuron-model</ExternalLink>{" "}
          source for preset tables.
        </p>

        <ParamBlock title="Membrane & spike generation">
          <Param
            name="r_base"
            typ="float, default 1.0"
            desc="Resting primary firing threshold (used outside the refractory window). Together with neuromodulator weights it sets how much integrated input must reach the axon hillock before a spike is considered."
          />
          <Param
            name="b_base"
            typ="float, default 1.2"
            desc="Post-cooldown threshold baseline, typically above r_base so the cell cannot immediately re-fire after refractory ends. Swaps with r_base in the refractory branch of the threshold logic."
          />
          <Param
            name="c"
            typ="int, default 10"
            desc="Refractory period in ticks. While (current_tick − t_last_fire) ≤ c, the higher threshold b is used; learning-window homeostasis also scales with c (see §2)."
          />
          <Param
            name="lambda_param"
            typ="float, default 20.0"
            desc="Membrane time constant for the leaky integrator: larger λ slows approach to the drive, smaller λ makes S track input faster (discrete update S ← S + (dt/λ)(−S + I_t))."
          />
          <Param
            name="p"
            typ="float, default 1.0"
            desc="Spike output amplitude O when the cell fires (O = p on spike, else 0). Propagates into presynaptic terminal u_o.info scaling downstream cable inputs."
          />
        </ParamBlock>

        <ParamBlock title="Cable & input integration">
          <Param
            name="delta_decay"
            typ="float, default 0.95"
            desc="Per-hop exponential decay δ for dendritic delay lines: contributions arriving after cable distance d are scaled by δ^d when integrated at the hillock (Phase C)."
          />
        </ParamBlock>

        <ParamBlock title="Plasticity & firing statistics">
          <Param
            name="eta_post"
            typ="float, default 0.01"
            desc="Postsynaptic learning rate η_post on u_i.info (and coupled plast/mod terms in the prediction-error vector). Scales Hebbian-style updates ∝ direction × ‖E_dir‖ × u_i.info."
          />
          <Param
            name="eta_retro"
            typ="float, default 0.01"
            desc="Retrograde learning rate η_retro applied to presynaptic terminals: adjusts u_o.info and u_o.mod from the first components of E_dir, closing a post→pre feedback loop."
          />
          <Param
            name="beta_avg"
            typ="float, default 0.999"
            desc="EMA decay for long-run firing estimate F_avg: F_avg ← β F_avg + (1−β) O. Feeds the homeostatic narrowing of the learning window t_ref (high firing → shorter causal STDP window)."
          />
        </ParamBlock>

        <ParamBlock title="Neuromodulator coupling (vectors length = num_neuromodulators)">
          <Param
            name="gamma"
            typ="ndarray, default [0.99, 0.995]"
            desc="Per-modulator EMA decay on M_vector: M ← γ⊙M + (1−γ)⊙total_adapt_signal. Smaller (1−γ) means faster tracking of chemosensory / volume-transmitted modulator influx."
          />
          <Param
            name="w_r"
            typ="ndarray, default [−0.2, 0.05]"
            desc="Sensitivity of dynamic primary threshold r to M_vector: r = r_base + w_r·M (after Phase A aggregation)."
          />
          <Param
            name="w_b"
            typ="ndarray, default [−0.2, 0.05]"
            desc="Sensitivity of post-refractory threshold b to M_vector: b = b_base + w_b·M."
          />
          <Param
            name="w_tref"
            typ="ndarray, default [−20, 10]"
            desc="Shifts the homeostatically computed learning window t_ref by neuromodulator state: longer/shorter STDP eligibility depending on M."
          />
          <Param
            name="num_neuromodulators"
            typ="int, default 2"
            desc="Dimensionality of M_vector, adapt receptors, and u_o.mod. In C. elegans lab wiring this is typically 2 (M0 stress-like, M1 reward-like channels)."
          />
        </ParamBlock>

        <ParamBlock title="Topology (fixed at build time in this lab)">
          <Param
            name="num_inputs"
            typ="int, default 10"
            desc="Number of postsynaptic slots (incoming synapses) allocated on the dendritic tree. The real connectome may require more; resizing implies rebuilding the PAULA network, not a live slider."
          />
        </ParamBlock>

        <ParamBlock title="Global synaptic / membrane bounds (constants)">
          <Param
            name="MAX_SYNAPTIC_WEIGHT"
            typ="2.0"
            desc="Clip ceiling for synaptic efficacy fields u_i.info and u_o.info during plasticity updates."
          />
          <Param
            name="MIN_SYNAPTIC_WEIGHT"
            typ="0.01"
            desc="Floor to avoid zero-weight deadlocks on excitatory synapses."
          />
          <Param
            name="MAX_MEMBRANE_POTENTIAL / MIN_MEMBRANE_POTENTIAL"
            typ="±20"
            desc="Hard clamp on S each tick for numerical stability after leaky integration and spike reset."
          />
        </ParamBlock>
      </section>

      {/* ——— Section 2: state, synapses, tick ——— */}
      <section id="guide-paula-dynamics" className="mb-10 scroll-mt-4">
        <h2 className="mb-1 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Section 2 · Runtime state, synapses, and tick()
        </h2>
        <p className="mb-5 max-w-3xl text-[13px] leading-relaxed text-zinc-400">
          These quantities evolve every PAULA tick. Several appear in the
          Neuron inspector as live-editable runtime fields; synapse/terminal
          tables edit u_i / u_o payloads per slot.
        </p>

        <ParamBlock title="Neuron state variables (per cell)">
          <Param
            name="S"
            typ="float"
            desc="Membrane potential at the axon hillock (leaky integrator state)."
          />
          <Param
            name="O"
            typ="float"
            desc="Instantaneous output — p on the spike tick, otherwise 0."
          />
          <Param
            name="t_last_fire"
            typ="float"
            desc="Simulation tick index of the last spike (drives refractory branch and STDP direction)."
          />
          <Param
            name="F_avg"
            typ="float"
            desc="Low-pass estimate of firing rate (β_avg EMA of O)."
          />
          <Param
            name="M_vector"
            typ="float[]"
            desc="Per-modulator internal state after γ-filtered aggregation of modulated inputs at synapses."
          />
          <Param
            name="r, b, t_ref"
            typ="float"
            desc="Dynamic threshold and learning-window width after neuromod + homeostasis. t_ref is clipped: lower bound 2c, upper bound c × num_inputs. Homeostatic baseline narrows the window when F_avg is high; w_tref·M shifts that curve."
          />
        </ParamBlock>

        <ParamBlock title="PostsynapticInputVector u_i (one per incoming synapse)">
          <Param
            name="u_i.info"
            typ="float"
            desc="Primary excitatory efficacy; appears in cable input V_local and in prediction error E_dir[0] for plasticity."
          />
          <Param
            name="u_i.plast"
            typ="float"
            desc="Parallel plasticity channel; co-scales dendritic drive with info and carries its own error component."
          />
          <Param
            name="u_i.adapt[k]"
            typ="float"
            desc="Receptor sensitivity to k-th neuromodulator concentration arriving at this synapse (elementwise product with external mod vector before summing into Phase A)."
          />
        </ParamBlock>

        <ParamBlock title="PresynapticOutputVector u_o (one per axon terminal)">
          <Param
            name="u_o.info"
            typ="float"
            desc="Spike amplitude broadcast to downstream partners (often initialised near p)."
          />
          <Param
            name="u_o.mod[k]"
            typ="float"
            desc="Modulator release profile from this terminal; contributes to partners’ M_vector aggregation."
          />
          <Param
            name="u_i_retro (terminal wrapper)"
            typ="float"
            desc="Retrograde susceptibility on the presynaptic point; couples to η_retro updates."
          />
          <Param
            name="potential (postsynaptic wrapper)"
            typ="float"
            desc="Local potential stored on PostsynapticPoint alongside u_i (used in network bookkeeping / inspection)."
          />
        </ParamBlock>

        <div className="mb-6">
          <h3 className="mb-2 font-mono text-sm text-accent">tick() phases (summary)</h3>
          <p className="mb-3 text-[13px] leading-relaxed text-zinc-400">
            Each call{" "}
            <code className="text-zinc-500">tick(external_inputs, current_tick, dt)</code>{" "}
            runs strictly ordered phases A→E on one neuron (network scheduling is
            in <code className="text-zinc-500">NeuronNetwork</code> in the same
            repo).
          </p>
          <ol className="list-decimal space-y-2 pl-5 text-[13px] leading-relaxed text-zinc-400">
            <li>
              <strong className="text-zinc-300">A — Neuromodulation.</strong> Sum
              modulator signals weighted by u_i.adapt; update M_vector EMA; refresh
              F_avg; compute dynamic r, b, and t_ref from M and firing homeostasis.
            </li>
            <li>
              <strong className="text-zinc-300">B — Input enqueue.</strong> For each
              active synapse, push delayed cable events keyed by arrival tick using
              u_i efficacy and cable distance tables.
            </li>
            <li>
              <strong className="text-zinc-300">C — Integration.</strong> Pop
              arrived events; sum contributions with δ^distance decay → hillock
              drive I_t.
            </li>
            <li>
              <strong className="text-zinc-300">D — Spike.</strong> Leaky update on
              S; compare to r or b depending on refractory state; emit spikes with
              amplitude p and enqueue axonal outputs.
            </li>
            <li>
              <strong className="text-zinc-300">E — Plasticity.</strong> Build
              prediction error E_dir between received packets and local u_i;
              choose STDP direction from (current_tick − t_last_fire) vs t_ref;
              update u_i (η_post) and retrogradely u_o (η_retro) with clipping.
            </li>
          </ol>
        </div>

        <div className="mb-6">
          <h3 className="mb-2 font-mono text-sm text-accent">Key equations (one tick)</h3>
          <p className="mb-2 text-[13px] leading-relaxed text-zinc-400">
            Notation: ⊙ is element-wise product, Σ_syn sums over synapses with
            non-zero drive, δ = <code className="text-zinc-500">delta_decay</code>
            , γ = <code className="text-zinc-500">gamma</code>, β ={" "}
            <code className="text-zinc-500">beta_avg</code>.
          </p>
          <EquationBlock
            label="Phase A — aggregate modulators & dynamics"
            lines={[
              "total_adapt = Σ_syn ( O_ext['mod'] ⊙ u_i.adapt )",
              "M ← γ ⊙ M + (1 − γ) ⊙ total_adapt",
              "F_avg ← β·F_avg + (1 − β)·O",
              "r ← r_base + w_r·M ,   b ← b_base + w_b·M",
              "normalised_F ← clip(F_avg · c, 0, 1)",
              "t_ref_homeo ← upper − (upper − lower) × normalised_F    (upper=c·num_inputs, lower=2c)",
              "t_ref ← clip( t_ref_homeo + w_tref·M , lower , upper )",
            ]}
          />
          <EquationBlock
            label="Phase B–C — delayed dendritic drive"
            lines={[
              "V_local = info_val × (u_i.info + u_i.plast)   (per active synapse)",
              "I_t = Σ_arrived ( V_initial × δ^distance )",
            ]}
          />
          <EquationBlock
            label="Phase D — leaky integrator & threshold"
            lines={[
              "S ← S + (dt/λ)(−S + I_t)     then clamp S to [S_min, S_max]",
              "threshold ← b  if (tick − t_last_fire) ≤ c   else r",
              "if S ≥ threshold and spacing ≥ c:  O ← p, S ← 0, t_last_fire ← tick",
            ]}
          />
          <EquationBlock
            label="Phase E — prediction error & learning"
            lines={[
              "E_dir = [ info_in − u_i.info , plast_in − u_i.plast , mod_in… ]",
              "direction ← +1 if (tick − t_last_fire) ≤ t_ref else −1",
              "Δu_i.info = η_post × direction × ‖E_dir‖ × u_i.info   (clip to weight bounds)",
              "u_o.info += η_retro × E_dir[0] × direction   (and mod slice similarly)",
            ]}
          />
        </div>
      </section>

      <section id="guide-paula-refs" className="scroll-mt-4 pb-6">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          References · blogs &amp; source repos
        </h2>
        <p className="mb-3 max-w-3xl text-[13px] leading-relaxed text-zinc-400">
          Full derivations, figures, and extended discussion are on the blog and
          in versioned code — not in this static lab bundle.
        </p>
        <ul className="space-y-2 text-[13px] text-zinc-300">
          <li>
            <span className="text-zinc-500">PAULA paper (model):</span>{" "}
            <ExternalLink href={URL.paulaPaper}>{URL.paulaPaper}</ExternalLink>
          </li>
          <li>
            <span className="text-zinc-500">ALERM framework (theory):</span>{" "}
            <ExternalLink href={URL.alermFramework}>{URL.alermFramework}</ExternalLink>
          </li>
          <li>
            <span className="text-zinc-500">Neuron implementation:</span>{" "}
            <ExternalLink href={URL.neuronModelRepo}>{URL.neuronModelRepo}</ExternalLink>{" "}
            — <code className="text-zinc-500">neuron/neuron.py</code>,{" "}
            <code className="text-zinc-500">neuron/network.py</code>
          </li>
          <li>
            <span className="text-zinc-500">C. elegans simulation stack (this lab):</span>{" "}
            <ExternalLink href={URL.activeInferenceRepo}>
              {URL.activeInferenceRepo}
            </ExternalLink>
          </li>
        </ul>
      </section>
    </div>
  );
}

function FurtherReadingIntro() {
  return (
    <p className="mt-2 text-[12px] leading-relaxed text-zinc-500">
      Start with the{" "}
      <ExternalLink href={URL.paulaPaper}>PAULA paper</ExternalLink> for the
      neuron-level story and{" "}
      <ExternalLink href={URL.alermFramework}>ALERM</ExternalLink> for how PAULA
      sits in the larger active-inference picture. Source lives in{" "}
      <ExternalLink href={URL.neuronModelRepo}>arterialist/neuron-model</ExternalLink>
      .
    </p>
  );
}

function ExternalLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="break-all text-accent underline-offset-2 hover:underline"
    >
      {children}
    </a>
  );
}

function EquationBlock({ label, lines }: { label: string; lines: string[] }) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-[11px] font-medium text-zinc-500">{label}</div>
      <pre className="overflow-x-auto rounded-md border border-zinc-800/80 bg-zinc-900/60 p-2 font-mono text-[11px] leading-snug text-zinc-300">
        {lines.join("\n")}
      </pre>
    </div>
  );
}

function ParamBlock({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-6">
      <h3 className="mb-3 border-b border-zinc-800/60 pb-1 font-mono text-sm text-zinc-200">
        {title}
      </h3>
      <dl className="space-y-4">{children}</dl>
    </div>
  );
}

function Param({
  name,
  typ,
  desc,
}: {
  name: string;
  typ: string;
  desc: React.ReactNode;
}) {
  return (
    <div>
      <dt className="font-mono text-xs text-accent">
        <code>{name}</code>{" "}
        <span className="font-sans text-[11px] font-normal text-zinc-500">
          {typ}
        </span>
      </dt>
      <dd className="mt-1 text-[13px] leading-relaxed text-zinc-400">{desc}</dd>
    </div>
  );
}
