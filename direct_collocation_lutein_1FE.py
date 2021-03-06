import casadi as ca
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

def offline_profile():
    # Degree of interpolating polynomial
    d = 5

    # Get collocation points
    tau_root = np.append(0, ca.collocation_points(d, 'radau'))

    # Coefficients of the collocation equation
    C = np.zeros((d+1,d+1))

    # Coefficients of the continuity equation
    D = np.zeros(d+1)

    # Coefficients of the quadrature function
    B = np.zeros(d+1)

    # Construct polynomial basis
    for j in range(d+1):
        # Construct Lagrange polynomials to get the polynomial basis at the collocation point
        p = np.poly1d([1])
        for r in range(d+1):
            if r != j:
                p *= np.poly1d([1, -tau_root[r]]) / (tau_root[j]-tau_root[r])

        # Evaluate the polynomial at the final time to get the coefficients of the continuity equation
        D[j] = p(1.0)

        # Evaluate the time derivative of the polynomial at all collocation points to get the coefficients of the continuity equation
        pder = np.polyder(p)
        for r in range(d+1):
            C[j,r] = pder(tau_root[r])

        # Evaluate the integral of the polynomial to get the coefficients of the quadrature function
        pint = np.polyint(p)
        B[j] = pint(1.0)

    # Time horizon
    T = 144.

    ########################################
    # ----- Defining Dynamic System  ----- #
    ########################################

    # Define vectors with names of states
    states     = ['Cx','Cn', 'Cl']
    nd         = len(states)
    xd         = ca.SX.sym('xd',nd)
    for i in range(nd):
        globals()[states[i]] = xd[i]

    # Define vectors with names of algebraic variables
    algebraics = []
    na         = len(algebraics)
    xa         = ca.SX.sym('xa',na)
    for i in range(na):
        globals()[algebraics[i]] = xa[i]

    # Define vectors with names of control variables
    inputs     = ['Fnin', 'I0']
    nu         = len(inputs)
    u          = ca.SX.sym("u",nu)
    for i in range(nu):
        globals()[inputs[i]] = u[i]

   
    # Define model parameter names and values
    modpar    = ['u_m', 'K_N', 'u_d', 'Y_nx', 'k_m', 'Kd', 'K_NL', 'Ks', 'Ki', 'Ksl', 'Kil', 'tau', 'Ka', 'L']
    modparval = [0.152, 30, 5.95e-3, 305, 0.35, 3.71e-3, 10, 142.8, 214.2, 320.6, 480.9, 0.120*1000, 0.0,  0.084]

    nmp         = len(modpar)
    uncertainty = ca.SX.sym('uncp', nmp)
    for i in range(nmp):
        globals()[modpar[i]] = ca.SX(modparval[i])

    # algebraic equations
    disc_int    = 11
    Izlist      = []

    def lb_law(tau, X, Ka, z, L, I0):
        Iz = I0 * (ca.exp(-(tau*X + Ka)*z) + ca.exp(-(tau*X + Ka)*(L-z)))
        return Iz

    Iz          = ca.SX.sym("Iz", disc_int)
    for i in range(disc_int):
        #print(i, i*L/(disc_int-1), L  )
        Iz[i] = ca.SX(lb_law(tau, Cx, Ka, i*L/(disc_int-1), L, I0))


    um_trap = (Iz[0]/((Iz[0] + Ks + (Iz[0]**2)/Ki)) + Iz[-1]/((Iz[-1] + Ks + (Iz[-1]**2)/Ki)))  
    km_trap = (Iz[0]/((Iz[0] + Ksl + (Iz[0]**2)/Kil)) + Iz[-1]/((Iz[-1] + Ksl + (Iz[-1]**2)/Kil))) 

    for i in range(1,disc_int-1):

        um_trap     += 2*Iz[i]/(Iz[i] + Ks + (Iz[i]**2)/Ki)
        km_trap     += 2*Iz[i]/(Iz[i] + Ksl + (Iz[i]**2)/Kil)

    u_0 = u_m/20 * um_trap
    k_0 = k_m/20 * km_trap
        
    # variable rate equations - model construction 
    dev_Cx  = u_0 * Cx * Cn/(Cn+K_N) - u_d*Cx
    dev_Cn  = - Y_nx * u_0 * Cx * Cn/(Cn+K_N) + Fnin 
    dev_Cl  = k_0 * Cn/(Cn+K_NL) * Cx - Kd * Cl * Cx

    ODEeq =  ca.vertcat(dev_Cx, dev_Cn, dev_Cl)

    # Constraint formulation
    g1  = Cx - 2.6
    g2  = -Cn + 150 
    g3  = -1.67 *Cx + Cl

    g = ca.vertcat(g1, g2, g3)

    # Continuous time dynamics
    f = ca.Function('f', [xd, u], [ODEeq, g], ['x', 'u'], ['ODEeq', 'LT'])

    # Control discretization
    N = 6                   # number of control intervals
    h = T/N                 # width of each finite element

    # Generating initial guesses
    #init_sobol = sobol_seq.i4_sobol_generate(nu + nd,N) # shape (steps_, 2)
    #ctrl_sobol = (lb + (ub-lb)*init_sobol[:,:]).T

    # Start with an empty NLP
    w=[]
    w0 = []
    lbw = []
    ubw = []
    J = 0
    g=[]
    lbg = []
    ubg = []

    # For plotting x and u given w
    x_plot = []
    u_plot = []

    # "Lift" initial conditions
    Xk = ca.MX.sym('X0', nd)                                                        # initialising state symbolically
    w.append(Xk)                                                                    # appending initial state to sequence
    lbw.append([0.27, 765., 0.0])                                                   # setting lower bound of initial state 
    ubw.append([0.27, 765., 0.0])                                                   # setting upper bound of initial state  (note that upper and lower bound are the same enforcing the constraint)
    w0.append([0.27, 765., 0.0])                                                    # setting initial guess for state
    x_plot.append(Xk)                                                               # appending symbolic variable to the plotting list
    Uk_prev = [0.001, 100] 

    # Formulate the NLP
    for k in range(N):
        # New NLP variable for the control
        Uk = ca.MX.sym('U_' + str(k), nu)                                           # defining symbolic variable u_k
        w.append(Uk)                                                                # appending to sequence to be optimised
        lbw.append([0.1, 100])                                                      # setting lower bounds for control 
        ubw.append([100., 1000])                                                    # setting upper bounds for the control 
        w0.append([30, 1000])                                                       # providing an initial guess for the control 
        u_plot.append(Uk)                                                           # appending symbolic variable for plotting 

        # add operational constraint 
        _, qk = f(Xk,Uk)                                                            # enforcing operational constraint
        g.append(qk)
        lbg.append([-np.inf, -np.inf, -np.inf])                                     # enforcing lower bounds 
        ubg.append([0, 0, 0])                                                       # enforcing upper bounds

        # State at collocation points
        Xc = []                                                                     # initialising list 
        for j in range(d):
            Xkj = ca.MX.sym('X_'+str(k)+'_'+str(j), nd)                             # defining a symbolic variable for the collocation point 
            Xc.append(Xkj)                                                          # appending state collocation variable to list for path constraint (next code block)
            w.append(Xkj)                                                           # appending state collocation variable to sequence to be optimised 
            lbw.append([0., 0., 0.])                                                # setting lower bound on the state collocation variable  
            ubw.append([100, 1e5, 100])                                             # setting upper bound on the state collocation variable
            w0.append([1.2, 800, 2])                                                # initialising a guess for the collocation variable 
        
        #g.append()

        # Loop over collocation points
        Xk_end = D[0]*Xk                                                            # declaring final state of element for continuity                                
        for j in range(1,d+1):
            # Expression for the state derivative at the collocation point           
            xp = C[0,j]*Xk                                                                                                      
            for r in range(d): xp = xp + C[r+1,j]*Xc[r]                              # representing time derivative of state via polynomial basis i.e. collocation equations

            # Append collocation equations
            fj, qj = f(Xc[j-1],Uk)                                                   # formulating expression of true time derivative with state and control as input and derivative and objective as return 
            g.append(h*fj - xp)                                                      # formulating constraint on collocation equations 
            lbg.append([0, 0, 0])                                                    # enforcing constraint via LB=UB
            ubg.append([0, 0, 0])                                                    # enforcing constraint via LB=UB
            # append operational constraints        
            g.append(qj)                                                            # appending constraint from function 
            lbg.append([-np.inf, -np.inf, -np.inf])                                 # enforcing lower bounds 
            ubg.append([0, 0, 0])                                                   # enforcing upper bounds

            # Add contribution to the end state
            Xk_end = Xk_end + D[j]*Xc[j-1];                                          # calculating state for end of finite element, for subsequent continuity constraint (Lagrange)

            # Add contribution to quadrature function (not required for my objective function)
            #J = J + B[j]*qj*h                                                       # calculating state for end of finite element, for subsequent continuity constraint (RK)                                          # forecasting contribution of state trajectory to objective function across a finite element using RK 

        # New NLP variable for state at end of interval
        Xk = ca.MX.sym('X_' + str(k+1), nd)                                         # defining new symbolic state 
        w.append(Xk)                                                                # appending state to optimisation sequence
        lbw.append([0., 0., 0.])                                                    # appending lower bounds
        ubw.append([100, 1e5, 100])                                                 # appending upper bounds
        w0.append([1.2, 800, 2])                                                    # appending initialisation of variable
        x_plot.append(Xk)                                                           # appending state to plot sequence

        # Add equality constraint
        g.append(Xk_end-Xk)                                                         # enforcing path continuity constraint 
        lbg.append([0, 0, 0])                                                       # enforcing constraint via LB=UB 
        ubg.append([0, 0, 0])                                                       # enforcing constraint via LB=UB

        if k == N-1:
            # add operational constraint 
            _, qk = f(Xk,Uk)                                                            # enforcing operational constraint
            g.append(qk)
            lbg.append([-np.inf, -np.inf, -np.inf])                                     # enforcing lower bounds 
            ubg.append([0, 0, 0])                                                       # enforcing upper bounds


        # Objective function (written as in the RL context, hence we minimise J in the problem)
        if k == N-1:
            J = J +  4 * Xk[-1]  - 1e-3*Xk[1]  - ((Uk[0]-Uk_prev[0]) * 4/10)**2  - ((Uk[1] - Uk_prev[1])* 9/1000 )**2  
        elif k > 0:

            J = J - ((Uk[0]-Uk_prev[0]) * 4/10)**2  - ((Uk[1] - Uk_prev[1]) * 9/1000)**2 
        else: J =J

        Uk_prev = Uk

    # Concatenate vectors
    w = ca.vertcat(*w)
    g = ca.vertcat(*g)
    x_plot = ca.horzcat(*x_plot)
    u_plot = ca.horzcat(*u_plot)
    w0 = np.concatenate(w0)
    lbw = np.concatenate(lbw)
    ubw = np.concatenate(ubw)
    lbg = np.concatenate(lbg)
    ubg = np.concatenate(ubg)

    # Create an NLP solver
    prob = {'f': -J, 'x': w, 'g': g}
    solver = ca.nlpsol('solver', 'ipopt', prob, {'ipopt':{'max_iter':10e3}});
    

    # Function to get x and u trajectories from w
    trajectories = ca.Function('trajectories', [w], [x_plot, u_plot], ['w'], ['x', 'u'])

    # Solve the NLP
    sol = solver(x0=w0, lbx=lbw, ubx=ubw, lbg=lbg, ubg=ubg)
    x_opt, u_opt = trajectories(sol['x'])
    x_opt = x_opt.full() # to numpy array
    u_opt = u_opt.full() # to numpy array

    g1 = x_opt [0] * -1.67 + x_opt[2]
    g2 = -x_opt[1] + 150
    g3 = x_opt[0] -2.6
    #print(g1, g2, g3)

    print('success', solver.stats()['success'])
    # action color map 
    Ecmap = sns.color_palette("Greens", n_colors=1, as_cmap = True)
    Acmap = sns.color_palette("rocket", n_colors=1, as_cmap = True)

    # state color map
    Acmap1 = sns.color_palette("Blues", n_colors=1, as_cmap = True)
    Ecmap1 = sns.color_palette("Set1_r", n_colors=1, as_cmap = True)
    Stepmap = sns.color_palette("Purples_r", n_colors=1, as_cmap = True)

    font = {'family' : 'serif',
    'weight' : 'bold','size'   : 40}

    plt.rc('font', **font)  # pass in the font dict as kwargs
    plt.rc('axes', titlesize=35)        # fontsize of the axes title
    plt.rc('axes', labelsize=40)        # fontsize of the x and y label 
    plt.rc('axes', linewidth=2)

    # Plot the result
    ep_length   = 7
    tgrid = np.linspace(0, N, N+1)
    colors = np.linspace(0,1,1)
    fig     = plt.figure(figsize = (60,30))
    ax = plt.subplot(3,2,1)
    plt.plot(tgrid, x_opt[0], linewidth= 2, label ='X' )
    plt.ylabel(r'Biomass Conc ($\mathregular{g L^{-1}}$)', labelpad=20)
    plt.xlabel('Control Interaction', labelpad=20)
    handles, labels = ax.get_legend_handles_labels()
    labels = [r'$X$']
    ax.legend(handles=handles, labels=labels, fontsize = 'large')
    plt.xlim(0, ep_length-1)
    # Initialize minor ticks
    ax.minorticks_on()
    # Turn off x-axis minor ticks
    ax.xaxis.set_tick_params(which='minor', bottom=False)
    ax.tick_params(which='major', length=12, width =2.5)
    ax.tick_params(which='minor', length=8, width =2.5)
    ax = plt.subplot(3,2,3)
    plt.plot(tgrid, x_opt[1], linewidth= 2, label ='N' )
    plt.ylabel(r'Nitrate Conc ($\mathregular{mg L^{-1}}$)', labelpad=20)
    plt.xlabel('Control Interaction', labelpad=20)
    handles, labels = ax.get_legend_handles_labels()
    labels = [r'$N$']
    ax.legend(handles=handles, labels=labels, fontsize = 'large')
    plt.xlim(0, ep_length-1)
    # Initialize minor ticks
    ax.minorticks_on()
    # Turn off x-axis minor ticks
    ax.xaxis.set_tick_params(which='minor', bottom=False)
    ax.tick_params(which='major', length=12, width =2.5)
    ax.tick_params(which='minor', length=8, width =2.5)
    ax = plt.subplot(3,2,5)
    plt.plot(tgrid, x_opt[2], linewidth= 2, label ='L' )
    plt.ylabel(r'Lutein Conc ($\mathregular{mg L^{-1}}$)', labelpad=20)
    plt.xlabel('Control Interaction', labelpad=20)
    handles, labels = ax.get_legend_handles_labels()
    labels = [r'$L$']
    ax.legend(handles=handles, labels=labels, fontsize = 'large')
    plt.xlim(0, ep_length-1)
    # Initialize minor ticks
    ax.minorticks_on()
    # Turn off x-axis minor ticks
    ax.xaxis.set_tick_params(which='minor', bottom=False)
    ax.tick_params(which='major', length=12, width =2.5)
    ax.tick_params(which='minor', length=8, width =2.5)
    ax = plt.subplot(3,2,2)
    plt.step(tgrid, np.append(np.nan, u_opt[0]), linewidth= 2, label ='F_in' )
    plt.ylabel('Nitrate Inflow ($\mathregular{mg h^{-1}}$)', labelpad=20)
    plt.xlabel('Control Interaction', labelpad=20)
    handles, labels = ax.get_legend_handles_labels()
    labels = [r'$F_{N_{in}}$']
    ax.legend(handles=handles, labels=labels, fontsize = 'large')
    plt.xlim(0, ep_length-1)
    # Initialize minor ticks
    ax.minorticks_on()
    # Turn off x-axis minor ticks
    ax.xaxis.set_tick_params(which='minor', bottom=False)
    ax.tick_params(which='major', length=12, width =2.5)
    ax.tick_params(which='minor', length=8, width =2.5)
    ax = plt.subplot(3,2,4)
    plt.step(tgrid, np.append(np.nan, u_opt[1]), linewidth= 2, label ='I_0' )
    plt.ylabel('Incident Light Intensity  ($\mathregular{\mu E}$)', labelpad=20)
    plt.xlabel('Control Interaction', labelpad=20)
    plt.xlim(0, ep_length-1)
    # Initialize minor ticks
    ax.minorticks_on()
    # Turn off x-axis minor ticks
    ax.xaxis.set_tick_params(which='minor', bottom=False)
    ax.tick_params(which='major', length=12, width =2.5)
    ax.tick_params(which='minor', length=8, width =2.5)
    handles, labels = ax.get_legend_handles_labels()
    labels = [r'$I_0$']
    ax.legend(handles=handles, labels=labels, fontsize = 'large')
    #ax.set_xlim([0, ep_length-1])
    #plt.grid()
    plt.subplots_adjust(hspace = .25)
    plt.subplots_adjust(wspace = .25)
    plt.savefig('C:\\Users\\g41606mm\\Dropbox\\Projects\\Python\\MPC\\CCPOProject\\LuteinCS\\Validation\\MPCopenloop_optim3.png')
    plt.close()

    print(type(u_opt[:,0]))
    return u_opt

offline_profile()